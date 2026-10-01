from unittest.mock import patch

from constance.test.unittest import override_config
from django.test import TestCase
from requests import Response
from rest_framework import status
from rest_framework.test import APIClient

from profile.models import Profile, User


class ProfileDetailTests(TestCase):
    def make_profile(self, *, memberdoc_id=None):
        suffix = Profile.objects.count() + 1
        user = User.objects.create_user(
            f"docuseal-profile-{suffix}@example.test", password="test-password"
        )
        profile = Profile.objects.create(
            user=user,
            first_name="DocuSeal",
            last_name="Member",
            state="active",
            memberdoc_id=memberdoc_id,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return profile, client

    def test_profile_returns_empty_document_links_without_submission(self):
        profile, client = self.make_profile()

        with override_config(ENABLE_DOCUSEAL_INTEGRATION=True):
            with patch(
                "api_general.views.get_docuseal_submission", return_value=None
            ) as get_submission:
                response = client.get("/api/profile/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["memberdocsLink"], [])
        get_submission.assert_called_once_with(profile)

    def test_profile_returns_empty_document_links_when_docuseal_is_unavailable(self):
        profile, client = self.make_profile(memberdoc_id=1)
        docuseal_response = Response()
        docuseal_response.status_code = status.HTTP_502_BAD_GATEWAY
        docuseal_response.url = "https://docuseal.example/api/submissions/1"

        with override_config(
            ENABLE_DOCUSEAL_INTEGRATION=True,
            DOCUSEAL_URL="https://docuseal.example/",
            DOCUSEAL_API_KEY="docuseal-token",
        ):
            with patch(
                "services.docuseal.requests.get", return_value=docuseal_response
            ) as get_submission:
                response = client.get("/api/profile/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["memberdocsLink"], [])
        get_submission.assert_called_once_with(
            url="https://docuseal.example/api/submissions/1",
            headers={"X-Auth-Token": "docuseal-token"},
        )
