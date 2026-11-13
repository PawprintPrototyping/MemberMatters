from allauth.account.adapter import DefaultAccountAdapter


class MemberMattersAccountAdapter(DefaultAccountAdapter):
    """Adapt AllAuth account flows to MemberMatters' existing signup flow."""

    def is_open_for_signup(self, request):
        # Registration remains owned by api_general.Register, which also
        # creates the required MemberMatters Profile and sends its emails.
        return False

    def get_user_display(self, user):
        return user.email

    def authenticate(self, request, **credentials):
        user = super().authenticate(request, **credentials)
        if user is not None and not getattr(user, "email_verified", True):
            return None
        return user
