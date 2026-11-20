from django.http import HttpRequest
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from allauth.headless.contrib.rest_framework.authentication import (
    JWTTokenAuthentication,
)


class HybridJWTAuthentication(BaseAuthentication):
    """Accept AllAuth JWTs and legacy Simple JWTs during the migration."""

    def authenticate(self, request: HttpRequest):
        if not request.headers.get("Authorization"):
            return None

        try:
            result = JWTTokenAuthentication().authenticate(request)
        except AuthenticationFailed:
            result = None

        if result is not None:
            return result

        return JWTAuthentication().authenticate(request)
