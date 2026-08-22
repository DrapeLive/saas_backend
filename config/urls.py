from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # OpenAPI schema + docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path(
        "api/",
        include(
            [
                # Auth + Users + Roles + Permissions
                path("", include("apps.accounts.urls", namespace="accounts")),
                # SuperAdmin — Company onboarding + lifecycle
                path("", include("apps.companies.urls", namespace="companies")),
                # Subscriptions (SuperAdmin plan management exposed via companies urls;
                # plan listing used by frontend pricing page)
                path("", include("apps.subscriptions.urls", namespace="subscriptions")),
                # Agents
                path("", include("apps.agents.urls", namespace="agents")),
                # Customers
                path("", include("apps.customers.urls", namespace="customers")),
                # Products + Inventory
                path("", include("apps.products.urls", namespace="products")),
                # Orders
                path("", include("apps.orders.urls", namespace="orders")),
                # Dispatch
                path("", include("apps.dispatch.urls", namespace="dispatch")),
                # Invoicing
                path("", include("apps.invoices.urls", namespace="invoicing")),
                # Payments + Outstanding Aging
                path("", include("apps.payments.urls", namespace="payments")),
                # Commissions
                path("", include("apps.commissions.urls", namespace="commissions")),
                # Tally Integration
                path(
                    "",
                    include(
                        "apps.tally_integrations.urls", namespace="tally_integration"
                    ),
                ),
                # Notifications
                path("", include("apps.notifications.urls", namespace="notifications")),
                # Audit Logs
                path("", include("apps.audits.urls", namespace="audit")),
            ]
        ),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
