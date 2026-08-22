from drf_spectacular.authentication import OpenApiAuthenticationExtension
from drf_spectacular.plumbing import build_bearer_security_scheme_object


class CustomJWTAuthenticationExtension(OpenApiAuthenticationExtension):
    """Exposes the project's JWT auth as a bearer scheme in the OpenAPI schema."""

    target_class = "apps.accounts.authentication.CustomJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return build_bearer_security_scheme_object(
            header_name="Authorization",
            token_prefix="Bearer",
        )
