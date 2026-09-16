import logging

import requests
from constance import config

logger = logging.getLogger("listmonk")


class ListmonkConfigurationError(ValueError):
    """Listmonk synchronization has incomplete local configuration."""


class ListmonkTransientError(RuntimeError):
    """Listmonk may accept the request after a retry."""


class ListmonkPermanentError(RuntimeError):
    """Listmonk rejected a request that should not be retried automatically."""


class ListmonkClient:
    def __init__(
        self,
        base_url,
        username,
        token,
        active_list_id,
        inactive_list_id,
        timeout,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = (username, token)
        self.active_list_id = active_list_id
        self.inactive_list_id = inactive_list_id
        self.timeout = timeout

    @classmethod
    def from_config(cls):
        try:
            active_list_id = int(config.LISTMONK_ACTIVE_LIST_ID)
            inactive_list_id = int(config.LISTMONK_INACTIVE_LIST_ID)
            timeout = int(config.LISTMONK_REQUEST_TIMEOUT)
        except (TypeError, ValueError) as error:
            raise ListmonkConfigurationError(
                "Listmonk list IDs and request timeout must be integers."
            ) from error

        if not config.LISTMONK_URL or not config.LISTMONK_API_TOKEN:
            raise ListmonkConfigurationError(
                "Listmonk URL and API token must be configured."
            )
        if active_list_id <= 0 or inactive_list_id <= 0:
            raise ListmonkConfigurationError(
                "Listmonk active and inactive list IDs must be positive integers."
            )
        if active_list_id == inactive_list_id:
            raise ListmonkConfigurationError(
                "Listmonk active and inactive list IDs must be different."
            )
        if timeout <= 0:
            raise ListmonkConfigurationError(
                "Listmonk request timeout must be positive."
            )

        return cls(
            base_url=config.LISTMONK_URL,
            username=config.LISTMONK_API_USERNAME,
            token=config.LISTMONK_API_TOKEN,
            active_list_id=active_list_id,
            inactive_list_id=inactive_list_id,
            timeout=timeout,
        )

    def synchronize_member(
        self,
        remote_subscriber_id,
        user_id,
        profile_id,
        email,
        name,
        desired_state,
    ):
        target_list_id, previous_list_id = self._lists_for_state(desired_state)
        subscriber = self._get_subscriber(remote_subscriber_id)
        if subscriber is None:
            subscriber = self._find_subscriber_by_email(email)

        attributes = {
            "membermatters_user_id": user_id,
            "membermatters_profile_id": profile_id,
            "member_state": desired_state,
        }
        if subscriber is None:
            subscriber = self._create_subscriber(
                email, name, target_list_id, attributes
            )
        else:
            subscriber_id = subscriber["id"]
            self._patch_subscriber(subscriber_id, email, name, attributes)
            self._move_subscriber(subscriber_id, target_list_id, previous_list_id)

        return subscriber["id"]

    def _lists_for_state(self, desired_state):
        if desired_state == "active":
            return self.active_list_id, self.inactive_list_id
        if desired_state == "inactive":
            return self.inactive_list_id, self.active_list_id
        raise ListmonkPermanentError(
            f"Unsupported Listmonk member state: {desired_state}."
        )

    def _get_subscriber(self, subscriber_id):
        if not subscriber_id:
            return None

        response = requests.get(
            f"{self.base_url}/api/subscribers/{subscriber_id}",
            auth=self.auth,
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        return self._response_data(response)

    def _find_subscriber_by_email(self, email):
        escaped_email = email.replace("'", "''")
        response = requests.get(
            f"{self.base_url}/api/subscribers",
            auth=self.auth,
            params={"query": f"subscribers.email = '{escaped_email}'", "per_page": 1},
            timeout=self.timeout,
        )
        data = self._response_data(response)
        results = data.get("results", [])
        return results[0] if results else None

    def _create_subscriber(self, email, name, target_list_id, attributes):
        response = requests.post(
            f"{self.base_url}/api/subscribers",
            auth=self.auth,
            json={
                "email": email,
                "name": name,
                "status": "enabled",
                "lists": [target_list_id],
                "attribs": attributes,
                "preconfirm_subscriptions": True,
            },
            timeout=self.timeout,
        )
        return self._response_data(response)

    def _patch_subscriber(self, subscriber_id, email, name, attributes):
        response = requests.patch(
            f"{self.base_url}/api/subscribers/{subscriber_id}",
            auth=self.auth,
            json={"email": email, "name": name, "attribs": attributes},
            timeout=self.timeout,
        )
        return self._response_data(response)

    def _move_subscriber(self, subscriber_id, target_list_id, previous_list_id):
        self._modify_list_membership(
            subscriber_id,
            action="remove",
            target_list_id=previous_list_id,
        )
        self._modify_list_membership(
            subscriber_id,
            action="add",
            target_list_id=target_list_id,
            status="confirmed",
        )

    def _modify_list_membership(
        self, subscriber_id, action, target_list_id, status=None
    ):
        payload = {
            "ids": [subscriber_id],
            "action": action,
            "target_list_ids": [target_list_id],
        }
        if status:
            payload["status"] = status

        response = requests.put(
            f"{self.base_url}/api/subscribers/lists",
            auth=self.auth,
            json=payload,
            timeout=self.timeout,
        )
        self._response_data(response)

    @staticmethod
    def _response_data(response):
        if response.status_code == 429 or response.status_code >= 500:
            raise ListmonkTransientError(
                f"Listmonk returned HTTP {response.status_code}."
            )
        if response.status_code >= 400:
            raise ListmonkPermanentError(
                f"Listmonk returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise ListmonkPermanentError(
                "Listmonk returned an invalid JSON response."
            ) from error
        if "data" not in payload:
            raise ListmonkPermanentError("Listmonk response did not contain data.")
        return payload["data"]
