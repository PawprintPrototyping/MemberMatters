from constance.test.unittest import override_config
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from profile.models import Profile, User


class ProxyVotingEndpointTests(TestCase):
    member_endpoints = (
        "/api/tools/meetings/",
        "/api/tools/members/",
        "/api/proxies/",
    )
    proxy_write_endpoints = (
        ("post", "/api/proxies/"),
        ("delete", "/api/proxies/999/"),
    )

    def make_user(self, state="active", staff=False):
        suffix = User.objects.count() + 1
        user = User.objects.create_user(
            f"proxy-endpoint-{suffix}@example.test",
            password="test-password",
        )
        user.staff = staff
        user.save(update_fields=["staff"])
        Profile.objects.create(
            user=user,
            first_name="Proxy",
            last_name=str(suffix),
            state=state,
        )
        return user

    def assert_gets_status(self, user, expected_status):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)

        for endpoint in self.member_endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(client.get(endpoint).status_code, expected_status)

    def test_unauthn_users_cannot_access_proxy_endpoints(self):
        with override_config(ENABLE_PROXY_VOTING=True):
            self.assert_gets_status(None, status.HTTP_401_UNAUTHORIZED)

            client = APIClient()
            for method, endpoint in self.proxy_write_endpoints:
                with self.subTest(method=method, endpoint=endpoint):
                    response = getattr(client, method)(endpoint, format="json")
                    self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_members_cannot_access_proxy_endpoints(self):
        user = self.make_user(state="inactive")

        with override_config(ENABLE_PROXY_VOTING=True):
            self.assert_gets_status(user, status.HTTP_403_FORBIDDEN)

            client = APIClient()
            client.force_authenticate(user=user)
            for method, endpoint in self.proxy_write_endpoints:
                with self.subTest(method=method, endpoint=endpoint):
                    response = getattr(client, method)(endpoint, format="json")
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_active_members_can_access_proxy_endpoints(self):
        user = self.make_user(state="active")

        with override_config(ENABLE_PROXY_VOTING=True):
            self.assert_gets_status(user, status.HTTP_200_OK)

    def test_staff_users_can_access_proxy_endpoints(self):
        user = self.make_user(state="inactive", staff=True)

        with override_config(ENABLE_PROXY_VOTING=True):
            self.assert_gets_status(user, status.HTTP_200_OK)

    def test_proxy_endpoints_are_disabled_with_the_feature(self):
        user = self.make_user(state="active")

        with override_config(ENABLE_PROXY_VOTING=False):
            self.assert_gets_status(user, status.HTTP_403_FORBIDDEN)

            client = APIClient()
            client.force_authenticate(user=user)
            for method, endpoint in self.proxy_write_endpoints:
                with self.subTest(method=method, endpoint=endpoint):
                    response = getattr(client, method)(endpoint, format="json")
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
