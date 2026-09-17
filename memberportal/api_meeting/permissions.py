from constance import config
from rest_framework import permissions


class ProxyVotingPermission(permissions.BasePermission):
    """Allow proxy-voting APIs only for the enabled feature's users."""

    message = "Proxy voting is not available to this user."

    def has_permission(self, request, view):
        if not config.ENABLE_PROXY_VOTING or not request.user.is_authenticated:
            return False

        profile = getattr(request.user, "profile", None)
        return request.user.is_staff or (
            profile is not None and profile.state == "active"
        )
