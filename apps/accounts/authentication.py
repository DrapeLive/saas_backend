from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import AccessToken


class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not user.is_active:
            from rest_framework.exceptions import AuthenticationFailed
            raise AuthenticationFailed("User account is disabled.")
        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, validated_token = result
            company_id = validated_token.get("company_id", None)

            # For agents, allow X-Company-Id header to override JWT context
            if user.role == "agent" and not company_id:
                header_company_id = request.META.get("HTTP_X_COMPANY_ID")
                if header_company_id:
                    from apps.agents.models import AgentCompanyMembership
                    if AgentCompanyMembership.objects.filter(
                        agent__user=user,
                        company_id=header_company_id,
                        status="active",
                    ).exists():
                        company_id = header_company_id

            if company_id:
                from apps.companies.models import Company
                try:
                    request.company = Company.objects.get(pk=company_id)
                except Company.DoesNotExist:
                    request.company = None
            else:
                request.company = None
            request.jwt_token = validated_token
        return result
