import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import user_logged_out
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve
from django.utils.module_loading import import_string
from django.contrib.sessions.middleware import SessionMiddleware
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from allauth.mfa import app_settings as mfa_settings
from allauth.mfa.models import Authenticator
from allauth.mfa.signals import authenticator_used
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    validate_totp_code,
)
from allauth.mfa.webauthn.forms import AddWebAuthnForm
from constance.test.unittest import override_config

from membermatters.mfa_policy import (
    ALLAUTH_PREFIX,
    MFA_LOGIN_PATH,
    MFA_SESSION_KEY,
    MFA_SETUP_ALLOWED_PATHS,
    AdminMFAMiddleware,
    admin_mfa_required,
    request_has_verified_mfa,
)
from profile.models import Profile, User


class MFAUserTestMixin:
    def make_user(self, email, staff=False):
        user = User.objects.create_user(email, password="test-password")
        if staff:
            user.staff = True
            user.save(update_fields=["staff"])
        return user

    def make_profile(self, email, staff=False):
        user = self.make_user(email, staff=staff)
        Profile.objects.create(
            user=user,
            first_name="MFA",
            last_name="Test",
            screen_name=f"mfa-{user.pk}",
        )
        return user

    def add_totp(self, user):
        secret = generate_totp_secret()
        TOTP.activate(user, secret)
        return secret

    def totp_code(self, secret):
        counter = int(time.time()) // mfa_settings.TOTP_PERIOD
        return format_hotp_value(hotp_value(secret, counter))


class AllAuthConfigurationTests(MFAUserTestMixin, TestCase):
    def test_headless_mfa_and_passkey_routes_are_available(self):
        self.assertTrue(settings.HEADLESS_ONLY)
        self.assertEqual(settings.HEADLESS_CLIENTS, ("browser", "app"))
        self.assertEqual(
            settings.HEADLESS_TOKEN_STRATEGY,
            "allauth.headless.tokens.strategies.jwt.JWTTokenStrategy",
        )
        self.assertCountEqual(
            settings.MFA_SUPPORTED_TYPES,
            ["totp", "webauthn", "recovery_codes"],
        )
        self.assertTrue(settings.MFA_PASSKEY_LOGIN_ENABLED)
        self.assertFalse(settings.MFA_TRUST_ENABLED)

        expected_routes = (
            ("/_allauth/browser/v1/auth/login", "login"),
            ("/_allauth/app/v1/auth/login", "login"),
            ("/_allauth/browser/v1/config", "config"),
            (
                "/_allauth/browser/v1/account/authenticators/totp",
                "manage_totp",
            ),
            (
                "/_allauth/app/v1/auth/webauthn/login",
                "login_webauthn",
            ),
        )
        for path, url_name in expected_routes:
            with self.subTest(path=path):
                self.assertEqual(resolve(path).url_name, url_name)

    def test_browser_login_returns_authenticated_headless_response(self):
        user = self.make_profile("allauth-browser@example.test")
        client = APIClient()

        response = client.post(
            "/_allauth/browser/v1/auth/login",
            {"email": user.email, "password": "test-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], status.HTTP_200_OK)
        self.assertTrue(body["meta"]["is_authenticated"])
        self.assertEqual(body["data"]["user"]["id"], user.pk)

    @override_settings(MFA_TOTP_TOLERANCE=1)
    def test_browser_login_stages_and_completes_totp(self):
        user = self.make_profile("allauth-browser-mfa@example.test")
        secret = self.add_totp(user)
        client = APIClient()

        pending = client.post(
            "/_allauth/browser/v1/auth/login",
            {"email": user.email, "password": "test-password"},
            format="json",
        )
        self.assertEqual(pending.status_code, status.HTTP_401_UNAUTHORIZED)
        flow = next(
            flow
            for flow in pending.json()["data"]["flows"]
            if flow["id"] == "mfa_authenticate"
        )
        self.assertTrue(flow["is_pending"])
        self.assertIn("totp", flow["types"])
        code = self.totp_code(secret)
        self.assertTrue(validate_totp_code(secret, code))

        completed = client.post(
            "/_allauth/browser/v1/auth/2fa/authenticate",
            {"code": code},
            format="json",
        )
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.json())
        self.assertTrue(completed.json()["meta"]["is_authenticated"])

    def test_app_login_mfa_token_authenticates_protected_api(self):
        user = self.make_profile("allauth-app-mfa@example.test", staff=True)
        secret = self.add_totp(user)
        client = APIClient()

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True), override_settings(
            HEADLESS_JWT_ALGORITHM="HS256",
            MFA_TOTP_TOLERANCE=1,
        ):
            pending = client.post(
                "/_allauth/app/v1/auth/login",
                {"email": user.email, "password": "test-password"},
                format="json",
            )
            self.assertEqual(pending.status_code, status.HTTP_401_UNAUTHORIZED)
            session_token = pending.json()["meta"]["session_token"]
            code = self.totp_code(secret)

            completed = client.post(
                "/_allauth/app/v1/auth/2fa/authenticate",
                {"code": code},
                format="json",
                HTTP_X_SESSION_TOKEN=session_token,
            )
            self.assertEqual(completed.status_code, status.HTTP_200_OK)
            access_token = completed.json()["meta"]["access_token"]

            profile = client.get(
                "/api/profile/",
                HTTP_AUTHORIZATION=f"Bearer {access_token}",
            )

        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.json()["id"], user.pk)

    def test_passwordless_webauthn_contract_is_enabled(self):
        self.assertIn("passwordless", AddWebAuthnForm.base_fields)
        self.assertTrue(settings.MFA_PASSKEY_LOGIN_ENABLED)


class MFAAuthenticationPolicyTests(MFAUserTestMixin, TestCase):
    def request_with_session(self, path, method="get", **kwargs):
        request = getattr(RequestFactory(), method)(path, **kwargs)
        SessionMiddleware(lambda _: HttpResponse()).process_request(request)
        request.session.save()
        return request

    def test_admin_mfa_required_only_matches_staff_when_enabled(self):
        staff = self.make_user("mfa-staff@example.test", staff=True)
        member = self.make_user("mfa-member@example.test")

        self.assertFalse(admin_mfa_required(staff))
        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            self.assertTrue(admin_mfa_required(staff))
            self.assertFalse(admin_mfa_required(member))
            self.assertFalse(admin_mfa_required(User()))

    def test_middleware_blocks_unverified_staff_requests(self):
        staff = self.make_user("middleware-staff@example.test", staff=True)
        request = self.request_with_session("/api/profile/")
        request.user = staff

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            response = AdminMFAMiddleware(lambda _: HttpResponse()).process_view(
                request, None, (), {}
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.content,
            b'{"code": "mfa_required", "detail": "Complete MFA before accessing this account."}',
        )

    def test_middleware_allows_setup_paths_and_completed_sessions(self):
        staff = self.make_user("middleware-allowed@example.test", staff=True)
        middleware = AdminMFAMiddleware(lambda _: HttpResponse())

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            for path in MFA_SETUP_ALLOWED_PATHS | {
                f"{ALLAUTH_PREFIX}browser/v1/auth/login",
            }:
                with self.subTest(path=path):
                    request = self.request_with_session(path)
                    request.user = staff
                    self.assertIsNone(middleware.process_view(request, None, (), {}))

            request = self.request_with_session(MFA_LOGIN_PATH, method="post")
            request.user = staff
            self.assertIsNone(middleware.process_view(request, None, (), {}))

            request = self.request_with_session("/api/profile/")
            request.user = staff
            request.session[MFA_SESSION_KEY] = str(staff.pk)
            self.assertIsNone(middleware.process_view(request, None, (), {}))

    def test_middleware_does_not_block_non_staff_or_options(self):
        member = self.make_user("middleware-member@example.test")
        middleware = AdminMFAMiddleware(lambda _: HttpResponse())

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            request = self.request_with_session("/api/profile/")
            request.user = member
            self.assertIsNone(middleware.process_view(request, None, (), {}))

            request = self.request_with_session("/api/profile/", method="options")
            request.user = member
            self.assertIsNone(middleware.process_view(request, None, (), {}))

    def test_unverified_staff_cannot_use_allauth_account_mutations(self):
        staff = self.make_user("middleware-account-mutation@example.test", staff=True)
        middleware = AdminMFAMiddleware(lambda _: HttpResponse())
        blocked_requests = (
            ("post", "/_allauth/browser/v1/account/password/change"),
            ("delete", "/_allauth/browser/v1/account/authenticators/webauthn"),
            ("post", "/_allauth/browser/v1/account/authenticators/recovery-codes"),
        )

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            for method, path in blocked_requests:
                with self.subTest(method=method, path=path):
                    request = self.request_with_session(path, method=method)
                    request.user = staff
                    response = middleware.process_view(request, None, (), {})
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                    self.assertEqual(
                        json.loads(response.content)["code"], "mfa_required"
                    )

        user = self.make_user("mfa-signals@example.test")
        request = self.request_with_session("/api/profile/")

        authenticator_used.send(
            sender=Authenticator,
            request=request,
            user=user,
            authenticator=None,
        )
        self.assertEqual(request.session[MFA_SESSION_KEY], str(user.pk))
        self.assertTrue(request.session.modified)
        self.assertTrue(request_has_verified_mfa(request, user))

        user_logged_out.send(sender=None, request=request, user=user)
        self.assertNotIn(MFA_SESSION_KEY, request.session)
        self.assertFalse(request_has_verified_mfa(request, user))

    def test_token_session_marker_is_accepted(self):
        user = self.make_user("mfa-token-session@example.test")
        token_session = self.request_with_session("/api/profile/").session
        token_session[MFA_SESSION_KEY] = str(user.pk)
        token_session.save()

        request = self.request_with_session("/api/profile/")
        request.auth = {"sid": token_session.session_key}
        self.assertTrue(request_has_verified_mfa(request, user))

    def test_app_enrollment_marks_the_token_backed_session(self):
        user = self.make_user("mfa-app-enrollment@example.test")
        token_request = self.request_with_session("/api/profile/")
        token_session = token_request.session
        token_session["_auth_user_id"] = str(user.pk)
        token_session.save()

        request = self.request_with_session(
            "/_allauth/app/v1/account/authenticators/totp",
            method="post",
            HTTP_X_SESSION_TOKEN=token_session.session_key,
        )
        request.user = AnonymousUser()
        middleware = AdminMFAMiddleware(lambda _: HttpResponse())
        middleware.process_view(request, None, (), {})
        middleware.process_response(request, HttpResponse(status=200))

        session_store = import_string(settings.SESSION_ENGINE + ".SessionStore")
        saved_session = session_store(session_key=token_session.session_key)
        self.assertEqual(saved_session[MFA_SESSION_KEY], str(user.pk))
        self.assertNotIn(MFA_SESSION_KEY, request.session)

        user = self.make_user("mfa-enrollment@example.test")
        middleware = AdminMFAMiddleware(lambda _: HttpResponse())

        for path in (
            "/_allauth/browser/v1/account/authenticators/totp",
            "/_allauth/app/v1/account/authenticators/webauthn",
        ):
            with self.subTest(path=path):
                request = self.request_with_session(path, method="post")
                request.user = user
                middleware.process_response(request, HttpResponse(status=200))
                self.assertEqual(request.session[MFA_SESSION_KEY], str(user.pk))

        request = self.request_with_session(
            "/_allauth/browser/v1/account/authenticators/totp", method="post"
        )
        request.user = user
        middleware.process_response(request, HttpResponse(status=400))
        self.assertNotIn(MFA_SESSION_KEY, request.session)


class DiscourseSSOMFAEnforcementTests(MFAUserTestMixin, TestCase):
    def signed_sso_data(self):
        secret = "sso-secret"
        payload = base64.b64encode(
            urlencode(
                {
                    "nonce": "nonce-1",
                    "return_sso_url": "https://discourse.example.test/session",
                }
            ).encode()
        ).decode()
        signature = hmac.new(
            secret.encode(), payload.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        return {"sso": payload, "sig": signature}, secret

    def test_authenticated_staff_cannot_issue_sso_handoff_without_mfa(self):
        user = self.make_user("discourse-staff@example.test", staff=True)
        Profile.objects.create(
            user=user,
            first_name="Discourse",
            last_name="Staff",
        )
        sso_data, secret = self.signed_sso_data()
        client = APIClient()
        client.force_login(user)

        with override_config(
            ENABLE_DISCOURSE_SSO_PROTOCOL=True,
            DISCOURSE_SSO_PROTOCOL_SECRET_KEY=secret,
            ENFORCE_MFA_FOR_ADMIN_USERS=True,
        ):
            response = client.post("/api/login/", {"sso": sso_data}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "mfa_required")
        self.assertNotIn("_auth_user_id", client.session)

    def test_staff_password_sso_login_returns_mfa_code(self):
        user = self.make_user("discourse-password@example.test", staff=True)
        sso_data, secret = self.signed_sso_data()
        client = APIClient()

        with override_config(
            ENABLE_DISCOURSE_SSO_PROTOCOL=True,
            DISCOURSE_SSO_PROTOCOL_SECRET_KEY=secret,
            ENFORCE_MFA_FOR_ADMIN_USERS=True,
        ):
            response = client.post(
                "/api/login/",
                {
                    "email": user.email,
                    "password": "test-password",
                    "sso": sso_data,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "mfa_required")

    def test_staff_with_mfa_marker_can_issue_sso_handoff(self):
        user = self.make_profile("discourse-positive@example.test", staff=True)
        sso_data, secret = self.signed_sso_data()
        client = APIClient()
        client.force_login(user)
        session = client.session
        session[MFA_SESSION_KEY] = str(user.pk)
        session.save()

        with override_config(
            ENABLE_DISCOURSE_SSO_PROTOCOL=True,
            DISCOURSE_SSO_PROTOCOL_SECRET_KEY=secret,
            ENFORCE_MFA_FOR_ADMIN_USERS=True,
        ):
            response = client.post("/api/login/", {"sso": sso_data}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("sso=", response.json()["redirect"])
        self.assertIn("sig=", response.json()["redirect"])


class LegacyTokenMFAEnforcementTests(MFAUserTestMixin, TestCase):
    def test_staff_obtain_and_refresh_are_blocked_when_mfa_is_enforced(self):
        user = self.make_user("token-staff@example.test", staff=True)
        client = APIClient()

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            obtain = client.post(
                "/api/token/obtain/",
                {"email": user.email, "password": "test-password"},
                format="json",
            )
            refresh = client.post(
                "/api/token/refresh/",
                {"refresh": str(RefreshToken.for_user(user))},
                format="json",
            )

        for response in (obtain, refresh):
            with self.subTest(response=response):
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.json()["code"], "mfa_required")

    def test_non_staff_tokens_continue_to_work_when_enforcement_is_enabled(self):
        user = self.make_user("token-member@example.test")
        client = APIClient()

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=True):
            obtain = client.post(
                "/api/token/obtain/",
                {"email": user.email, "password": "test-password"},
                format="json",
            )
            refresh = client.post(
                "/api/token/refresh/",
                {"refresh": obtain.json()["refresh"]},
                format="json",
            )

        self.assertEqual(obtain.status_code, status.HTTP_200_OK)
        self.assertIn("access", obtain.json())
        self.assertEqual(refresh.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh.json())

    def test_staff_tokens_work_when_enforcement_is_disabled(self):
        user = self.make_user("token-disabled@example.test", staff=True)
        client = APIClient()

        with override_config(ENFORCE_MFA_FOR_ADMIN_USERS=False):
            response = client.post(
                "/api/token/obtain/",
                {"email": user.email, "password": "test-password"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.json())
