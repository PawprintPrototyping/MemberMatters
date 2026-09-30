from unittest.mock import patch

from constance.test.unittest import override_config
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from profile.models import Profile, User


class ProfileDetailTests(TestCase):
    def test_profile_returns_empty_document_links_without_submission(self):
        user = User.objects.create_user(
            "docuseal-profile@example.test", password="test-password"
        )
        profile = Profile.objects.create(
            user=user,
            first_name="DocuSeal",
            last_name="Member",
            state="active",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        with override_config(ENABLE_DOCUSEAL_INTEGRATION=True):
            with patch(
                "api_general.views.get_docuseal_submission", return_value=None
            ) as get_submission:
                response = client.get("/api/profile/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["memberdocsLink"], [])
        get_submission.assert_called_once_with(profile)
