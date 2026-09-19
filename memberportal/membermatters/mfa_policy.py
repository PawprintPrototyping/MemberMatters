from __future__ import annotations

from django.conf import settings
from django.contrib.auth.signals import user_logged_out
from django.http import HttpRequest, JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.dispatch import receiver
from django.utils.module_loading import import_string

from allauth.mfa.signals import authenticator_used
from constance import config

MFA_SESSION_KEY = "membermatters.mfa_verified_user"
ALLAUTH_PREFIX = "/_allauth/"
MFA_SETUP_ALLOWED_PATHS = {
    "/api/logout/",
    "/api/config/",
    "/api/login/",
    "/api/token/obtain/",
    "/api/token/refresh/",
}


def admin_mfa_required(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_staff", False)
        and config.ENFORCE_MFA_FOR_ADMIN_USERS
    )


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
        return session_store(session_key=session_id)
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

        if request.path.startswith(ALLAUTH_PREFIX):
            # AllAuth needs these endpoints to remain available for first-time
            # enrollment when a staff member has no authenticator yet.
            return None

        user = request.user
        if not user.is_authenticated:
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
            and getattr(request.user, "is_authenticated", False)
        ):
            # Enrollment verifies the TOTP code or WebAuthn assertion. Treat
            # that successful ceremony as MFA completion for this session.
            request.session[MFA_SESSION_KEY] = str(request.user.pk)
            request.session.modified = True
        return response
