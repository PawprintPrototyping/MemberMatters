from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class StaffMFAEnforcedTokenObtainPairView(TokenObtainPairView):
    """Prevent the legacy JWT endpoint from bypassing enforced staff MFA."""

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from membermatters.mfa_policy import admin_mfa_required

        if admin_mfa_required(serializer.user):
            return Response(
                {
                    "code": "mfa_required",
                    "detail": "Use the AllAuth login endpoint to complete MFA.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class StaffMFAEnforcedTokenRefreshView(TokenRefreshView):
    """Prevent legacy refresh tokens from bypassing enforced staff MFA."""

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from membermatters.mfa_policy import admin_mfa_required

        refresh = RefreshToken(request.data["refresh"])
        user_id = refresh.get(settings.SIMPLE_JWT["USER_ID_CLAIM"])
        user = get_user_model().objects.filter(pk=user_id).first()
        if admin_mfa_required(user):
            return Response(
                {
                    "code": "mfa_required",
                    "detail": "Use the AllAuth login endpoint to complete MFA.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(serializer.validated_data, status=status.HTTP_200_OK)
