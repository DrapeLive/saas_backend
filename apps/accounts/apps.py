from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        # Register the JWT auth extension for drf-spectacular schema generation
        from apps.accounts import openapi  # noqa: F401
