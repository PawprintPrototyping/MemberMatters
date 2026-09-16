from unittest.mock import Mock, patch

from constance.test.unittest import override_config
from django.test import TestCase

from services.listmonk import (
    ListmonkClient,
    ListmonkConfigurationError,
    ListmonkPermanentError,
    ListmonkTransientError,
)


class ListmonkClientTests(TestCase):
    config = {
        "LISTMONK_URL": "https://listmonk.example.test/",
        "LISTMONK_API_USERNAME": "api_user",
        "LISTMONK_API_TOKEN": "token",
        "LISTMONK_ACTIVE_LIST_ID": 10,
        "LISTMONK_INACTIVE_LIST_ID": 20,
        "LISTMONK_REQUEST_TIMEOUT": 5,
    }

    def response(self, status_code, data=None, json_error=None):
        response = Mock(status_code=status_code)
        if json_error:
            response.json.side_effect = json_error
        else:
            response.json.return_value = {"data": data}
        return response

    def test_from_config_builds_client_and_validates_required_values(self):
        with override_config(**self.config):
            client = ListmonkClient.from_config()

        self.assertEqual(client.base_url, "https://listmonk.example.test")
        self.assertEqual(client.auth, ("api_user", "token"))
        self.assertEqual((client.active_list_id, client.inactive_list_id), (10, 20))
        self.assertEqual(client.timeout, 5)

        invalid = {
            **self.config,
            "LISTMONK_ACTIVE_LIST_ID": 10,
            "LISTMONK_INACTIVE_LIST_ID": 10,
        }
        with override_config(**invalid):
            with self.assertRaisesMessage(
                ListmonkConfigurationError,
                "Listmonk active and inactive list IDs must be different.",
            ):
                ListmonkClient.from_config()

    def test_synchronize_creates_missing_subscriber_in_active_list(self):
        client = ListmonkClient(
            "https://listmonk.example.test", "user", "token", 10, 20, 5
        )
        lookup = self.response(200, {"results": []})
        created = self.response(200, {"id": 99})

        with patch("services.listmonk.requests.get", return_value=lookup) as get:
            with patch("services.listmonk.requests.post", return_value=created) as post:
                subscriber_id = client.synchronize_member(
                    remote_subscriber_id=None,
                    user_id=1,
                    profile_id=2,
                    email="member@example.test",
                    name="Member Example",
                    desired_state="active",
                )

        self.assertEqual(subscriber_id, 99)
        get.assert_called_once_with(
            "https://listmonk.example.test/api/subscribers",
            auth=("user", "token"),
            params={
                "query": "subscribers.email = 'member@example.test'",
                "per_page": 1,
            },
            timeout=5,
        )
        post.assert_called_once_with(
            "https://listmonk.example.test/api/subscribers",
            auth=("user", "token"),
            json={
                "email": "member@example.test",
                "name": "Member Example",
                "status": "enabled",
                "lists": [10],
                "attribs": {
                    "membermatters_user_id": 1,
                    "membermatters_profile_id": 2,
                    "member_state": "active",
                },
                "preconfirm_subscriptions": True,
            },
            timeout=5,
        )

    def test_synchronize_existing_subscriber_updates_contact_and_moves_lists(self):
        client = ListmonkClient(
            "https://listmonk.example.test", "user", "token", 10, 20, 5
        )
        subscriber = self.response(200, {"id": 99})
        response = self.response(200, True)

        with patch("services.listmonk.requests.get", return_value=subscriber) as get:
            with patch(
                "services.listmonk.requests.patch", return_value=response
            ) as patch_request:
                with patch(
                    "services.listmonk.requests.put", return_value=response
                ) as put:
                    subscriber_id = client.synchronize_member(
                        remote_subscriber_id=99,
                        user_id=1,
                        profile_id=2,
                        email="new@example.test",
                        name="Updated Member",
                        desired_state="inactive",
                    )

        self.assertEqual(subscriber_id, 99)
        get.assert_called_once_with(
            "https://listmonk.example.test/api/subscribers/99",
            auth=("user", "token"),
            timeout=5,
        )
        patch_request.assert_called_once_with(
            "https://listmonk.example.test/api/subscribers/99",
            auth=("user", "token"),
            json={
                "email": "new@example.test",
                "name": "Updated Member",
                "attribs": {
                    "membermatters_user_id": 1,
                    "membermatters_profile_id": 2,
                    "member_state": "inactive",
                },
            },
            timeout=5,
        )
        self.assertEqual(put.call_count, 2)
        self.assertEqual(
            put.call_args_list[0].kwargs["json"],
            {
                "ids": [99],
                "action": "remove",
                "target_list_ids": [10],
            },
        )
        self.assertEqual(
            put.call_args_list[1].kwargs["json"],
            {
                "ids": [99],
                "action": "add",
                "target_list_ids": [20],
                "status": "confirmed",
            },
        )

    def test_missing_remote_subscriber_falls_back_to_escaped_email_lookup(self):
        client = ListmonkClient(
            "https://listmonk.example.test", "user", "token", 10, 20, 5
        )
        missing = self.response(404)
        lookup = self.response(200, {"results": [{"id": 88}]})
        response = self.response(200, True)

        with patch(
            "services.listmonk.requests.get", side_effect=[missing, lookup]
        ) as get:
            with patch("services.listmonk.requests.patch", return_value=response):
                with patch("services.listmonk.requests.put", return_value=response):
                    client.synchronize_member(
                        remote_subscriber_id=99,
                        user_id=1,
                        profile_id=2,
                        email="o'hara@example.test",
                        name="Member",
                        desired_state="active",
                    )

        self.assertEqual(
            get.call_args_list[1].kwargs["params"]["query"],
            "subscribers.email = 'o''hara@example.test'",
        )

    def test_response_errors_are_classified_without_leaking_response_body(self):
        for status_code, exception_class in (
            (429, ListmonkTransientError),
            (503, ListmonkTransientError),
            (400, ListmonkPermanentError),
        ):
            with self.subTest(status_code=status_code):
                with self.assertRaises(exception_class):
                    ListmonkClient._response_data(self.response(status_code))

        with self.assertRaises(ListmonkPermanentError):
            ListmonkClient._response_data(
                self.response(200, json_error=ValueError("invalid JSON"))
            )
        missing_data = Mock(status_code=200)
        missing_data.json.return_value = {}
        with self.assertRaises(ListmonkPermanentError):
            ListmonkClient._response_data(missing_data)
