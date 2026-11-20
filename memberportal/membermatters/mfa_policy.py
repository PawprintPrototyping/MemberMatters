from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_out
from django.http import HttpRequest, JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.utils.module_loading import import_string
from django.dispatch import receiver

from rest_framework.exceptions import AuthenticationFailed

from allauth.headless.tokens.strategies.jwt.internal import session_key_from_sid
from allauth.mfa.signals import authenticator_used
from constance import config

MFA_SESSION_KEY = "membermatters.mfa_verified_user"
ALLAUTH_PREFIX = "/_allauth/"
MFA_LOGIN_PATH = "/api/login/"
MFA_SETUP_ALLOWED_PATHS = {
    "/api/logout/",
    "/api/config/",
    "/api/token/obtain/",
    "/api/token/refresh/",
}


def admin_mfa_required(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_staff", False)
        and config.ENFORCE_MFA_FOR_ADMIN_USERS
    )


def _capture_allauth_app_session(request: HttpRequest) -> None:
    session_key = request.headers.get("X-Session-Token")
    user = None

    if not session_key:
        try:
            from allauth.headless.contrib.rest_framework.authentication import (
                JWTTokenAuthentication,
            )

            authentication = JWTTokenAuthentication().authenticate(request)
            if authentication:
                user, token = authentication
                if isinstance(token, dict):
                    session_key = token.get("sid")
        except AuthenticationFailed:
            return

    if not session_key:
        return

    setattr(request, "_membermatters_mfa_session_key", session_key)
    if not getattr(request, "auth", None):
        request.auth = {"sid": session_key}
    session_store = import_string(settings.SESSION_ENGINE + ".SessionStore")
    token_session = session_store(session_key=session_key)
    if user is None:
        user_id = token_session.get("_auth_user_id")
        if user_id is not None:
            user = get_user_model().objects.filter(pk=user_id).first()
    setattr(request, "_membermatters_mfa_user", user)


def _allauth_path_allowed_for_unverified_staff(path: str, method: str) -> bool:
    normalized_path = path.rstrip("/")
    suffix = "/" + normalized_path.split("/v1/", 1)[-1].lstrip("/")

    match suffix:
        case (
            "/auth/login"
            | "/auth/2fa/authenticate"
            | "/auth/webauthn/login"
            | "/auth/webauthn/authenticate"
        ):
            return True
        case "/config" if method == "GET":
            return True
        case "/auth/session" if method == "DELETE":
            return True
        case "/account/authenticators" if method == "GET":
            return True
        case (
            "/account/authenticators/totp" | "/account/authenticators/webauthn"
        ) if method in {"GET", "POST"}:
            return True
        case _:
            return False


def _session_has_mfa_marker(session, user) -> bool:
    return str(session.get(MFA_SESSION_KEY, "")) == str(user.pk)


def _session_for_token(request: HttpRequest):
    auth = getattr(request, "auth", None)
    candidates = [auth]
    if isinstance(auth, tuple):
        candidates.extend(auth)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        session_id = candidate.get("sid")
        if not session_id:
            continue
        session_store = import_string(settings.SESSION_ENGINE + ".SessionStore")
        raw_session = session_store(session_key=session_id)
        if raw_session.exists(session_id):
            return raw_session

        decoded_session_id = session_key_from_sid(session_id)
        if decoded_session_id:
            return session_store(session_key=decoded_session_id)
    return None


def request_has_verified_mfa(request: HttpRequest, user) -> bool:
    if _session_has_mfa_marker(request.session, user):
        return True

    token_session = _session_for_token(request)
    return bool(token_session and _session_has_mfa_marker(token_session, user))


@receiver(authenticator_used)
def mark_mfa_session(sender, request, user, **kwargs):
    if request is not None and user is not None:
        request.session[MFA_SESSION_KEY] = str(user.pk)
        request.session.modified = True


@receiver(user_logged_out)
def clear_mfa_session(sender, request, user, **kwargs):
    if request is not None:
        request.session.pop(MFA_SESSION_KEY, None)


class AdminMFAMiddleware(MiddlewareMixin):
    """Require completed AllAuth MFA for staff when the flag is enabled."""

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method == "OPTIONS":
            return None

        is_allauth_path = request.path.startswith(ALLAUTH_PREFIX)
        if is_allauth_path:
            # Capture the app session before AllAuth temporarily swaps and
            # restores request.session inside its headless decorator.
            _capture_allauth_app_session(request)

        if request.path == MFA_LOGIN_PATH and request.method == "POST":
            # The login endpoint must be reachable for first-factor requests;
            # Login.post enforces MFA for any already-authenticated staff user.
            return None

        user = request.user
        if not user.is_authenticated:
            captured_user = getattr(request, "_membermatters_mfa_user", None)
            if captured_user is not None:
                user = captured_user
                request.user = user
            else:
                try:
                    from membermatters.authentication import HybridJWTAuthentication

                    authentication = HybridJWTAuthentication().authenticate(request)
                    if authentication:
                        user, request.auth = authentication
                        request.user = user
                except Exception:
                    user = request.user

        if not admin_mfa_required(user):
            return None

        if request.path in MFA_SETUP_ALLOWED_PATHS:
            return None

        if request_has_verified_mfa(request, user):
            return None

        if is_allauth_path and _allauth_path_allowed_for_unverified_staff(
            request.path, request.method
        ):
            return None

        return JsonResponse(
            {
                "code": "mfa_required",
                "detail": "Complete MFA before accessing this account.",
            },
            status=403,
        )

    def process_response(self, request, response):
        if (
            request.path.startswith(ALLAUTH_PREFIX)
            and request.method == "POST"
            and (
                request.path.endswith("/account/authenticators/totp")
                or request.path.endswith("/account/authenticators/webauthn")
            )
            and response.status_code < 300
        ):
            # Enrollment verifies the TOTP code or WebAuthn assertion. For app
            # clients, write to the token-backed session captured in
            # process_view; AllAuth has restored the original request session
            # by the time this response hook runs.
            user = getattr(request, "_membermatters_mfa_user", None)
            session_key = getattr(request, "_membermatters_mfa_session_key", None)
            if session_key:
                session_store = import_string(settings.SESSION_ENGINE + ".SessionStore")
                session = session_store(session_key=session_key)
                if user is not None:
                    session[MFA_SESSION_KEY] = str(user.pk)
                    session.save()
            elif getattr(request.user, "is_authenticated", False):
                request.session[MFA_SESSION_KEY] = str(request.user.pk)
                request.session.modified = True
        return response
