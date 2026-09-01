from pathlib import Path

import dj_database_url
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = config("SECRET_KEY")

DEBUG = config("DEBUG")

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    # Apps
    "apps.accounts",
    "apps.agents",
    "apps.audits",
    "apps.commissions",
    "apps.customers",
    "apps.dispatch",
    "apps.invoices",
    "apps.notifications",
    "apps.orders",
    "apps.payments",
    "apps.products",
    "apps.subscriptions",
    "apps.tally_integrations",
    "apps.companies",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    # "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.CompanyScopeMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "accounts.User"


DATABASE_URL = config("DATABASE_URL", default="")

if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Test Configuration — use SQLite in-memory, disable throttling
# ---------------------------------------------------------------------------
import sys

TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.CustomJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "100/minute",
        "login": "5/minute",
        "signup": "3/minute",
        "password_reset": "3/hour",
    },
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    # JSON-only API: test client posts nested payloads as JSON by default
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "EXCEPTION_HANDLER": "apps.accounts.views.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ---------------------------------------------------------------------------
# OpenAPI schema (drf-spectacular)
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Lable API",
    "DESCRIPTION": (
        "REST API for the Lable platform — a multi-tenant textile "
        "wholesale management suite covering customers, products, inventory, "
        "orders, dispatch, invoicing, payments, commissions and Tally sync.\n\n"
        "### Authentication\n"
        "All endpoints except **Authentication** (login / signup / refresh / "
        "password reset) require a bearer token:\n\n"
        "    Authorization: Bearer <access-token>\n\n"
        "Obtain a token pair from `POST /api/auth/login` or `POST /api/auth/signup`. "
        "Access tokens expire after 24 hours; use `POST /api/auth/refresh` to renew. "
        'Click **Authorize** and paste the access token to enable "Try it out" on '
        "authenticated endpoints.\n\n"
        "### Company scoping\n"
        "Every business endpoint is scoped to a single tenant company. The company "
        "is resolved from the JWT `company_id` claim. Agents whose token carries no "
        "`company_id` claim may select a company by sending the `X-Company-Id` "
        "header (must match an active membership).\n\n"
        "### Roles\n"
        "`superadmin` — platform operator only. `admin` — company owner. "
        "`subadmin` — company staff. `agent` — field sales agent. `customer` — "
        "customer portal (not exposed by this API).\n\n"
        "### Errors\n"
        "All error responses share a flat envelope returned by the global "
        "exception handler:\n\n"
        '    {\\"detail\\": \\"Human-readable error message.\\"}\n\n'
        "Status codes: `400` validation / business-rule failure, `401` missing or "
        "invalid token, `403` forbidden role, `404` not found in the current "
        "company, `409` conflict, `429` rate limited."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api",
    # Developer-facing API domains. Order controls the Swagger sidebar.
    "TAGS": [
        {
            "name": "Authentication",
            "description": "Login, signup, token refresh, logout, password and agent onboarding.",
        },
        {
            "name": "Accounts",
            "description": "Company users, sub-admins, invitations and the company setup wizard.",
        },
        {
            "name": "Companies",
            "description": "Super-admin lifecycle management of tenant companies.",
        },
        {
            "name": "Agents",
            "description": "Agent memberships, approvals, performance and leaderboards.",
        },
        {
            "name": "Customers",
            "description": "Customer profiles, documents, communication logs and customer analytics.",
        },
        {
            "name": "Products",
            "description": "Products, color variants, QR scans and inventory listings.",
        },
        {"name": "Categories", "description": "Hierarchical product categories."},
        {
            "name": "Size Charts",
            "description": "Reusable size charts attached to products.",
        },
        {
            "name": "Stock",
            "description": "Stock movement ledger and manual adjustments.",
        },
        {
            "name": "Orders",
            "description": "Orders, workflow status, packing, approvals, offline sync and signatures.",
        },
        {
            "name": "Dispatch",
            "description": "Dispatch records and delivery confirmation.",
        },
        {
            "name": "Invoices",
            "description": "Invoices, credit/debit notes, voiding and PDF download.",
        },
        {
            "name": "Payments",
            "description": "Payments, outstanding aging reports and payment reminders.",
        },
        {
            "name": "Plans",
            "description": "Subscription pricing tiers managed by the super-admin.",
        },
        {
            "name": "Subscriptions",
            "description": "Company subscriptions, upgrades, extensions and usage.",
        },
        {
            "name": "Commissions",
            "description": "Commission plans, slabs, category rates and entry settlement.",
        },
        {
            "name": "Notifications",
            "description": "Notification templates and dispatch records.",
        },
        {
            "name": "Audit Logs",
            "description": "Read-only audit trail of company activity.",
        },
        {
            "name": "Tally Integration",
            "description": "Tally sync logs, ledger mappings and connection actions.",
        },
        {
            "name": "Admin",
            "description": "Company admin dashboards, analytics and business stats.",
        },
        {"name": "Super Admin", "description": "Platform-level dashboard."},
    ],
    # Stable, meaningful enum component names. Keys map the exact `(value,
    # label)` choice set (via TextChoices/Enum class path, or a bare value list
    # when the source has no reusable class) to a human-friendly name.
    "ENUM_NAME_OVERRIDES": {
        # Accounts / roles
        "RoleEnum": "apps.accounts.models.RoleType",
        # Companies
        "CompanyStatusEnum": "apps.companies.models.CompanyStatus",
        # Customers
        "CustomerStatusEnum": "apps.customers.models.CustomerProfile.CustomerStatus",
        "CustomerSegmentEnum": "apps.customers.models.CustomerProfile.CustomerSegment",
        "GstinStatusEnum": "apps.customers.models.GstStatus",
        "DocTypeEnum": "apps.customers.models.CustomerDocument.DocType",
        "CommunicationChannelEnum": "apps.customers.models.CustomerCommunicationLog.ChannelType",
        # Products
        "ProductStatusEnum": "apps.products.models.Product.ProductStatus",
        "StockMovementTypeEnum": "apps.products.models.StockMovement.MovementType",
        # Orders
        "OrderStatusEnum": "apps.orders.models.OrderStatus",
        "PackingStatusEnum": "apps.orders.models.PackingStatus",
        "OrderApprovalActionEnum": ["approve", "reject"],
        # Invoices
        "InvoiceTypeEnum": "apps.invoices.models.InvoiceType",
        "InvoiceStatusEnum": "apps.invoices.models.InvoiceStatus",
        # Payments
        "PaymentModeEnum": "apps.payments.models.PaymentMode",
        "PaymentReminderChannelEnum": ["whatsapp", "email", "both"],
        # Plans / subscriptions
        "PlanTierEnum": "apps.subscriptions.models.PlanTier",
        "BillingCycleEnum": "apps.subscriptions.models.BillingCycle",
        "SubscriptionStatusEnum": "apps.subscriptions.models.SubscriptionStatus",
        "SubscriptionEventTypeEnum": "apps.subscriptions.models.SubscriptionEvent.EventType",
        # Agents
        "AgentMembershipStatusEnum": "apps.agents.models.AgentCompanyMembership.MembershipStatus",
        "InvitationMethodEnum": [
            ("whatsapp", "WhatsApp"),
            ("email", "Email"),
            ("qr_code", "QR Code"),
            ("in_app", "In-App"),
        ],
        "InvitationStatusEnum": "apps.agents.models.AgentInvitation.InviteStatus",
        # Commissions
        "CommissionEntryStatusEnum": "apps.commissions.models.CommissionEntry.EntryStatus",
        # Notifications
        "NotificationChannelEnum": "apps.notifications.models.NotificationChannel",
        "NotificationStatusEnum": "apps.notifications.models.NotificationStatus",
        "NotificationTemplateEventTypeEnum": "apps.notifications.models.NotificationTemplate.EventType",
        # Tally
        "TallyDirectionEnum": "apps.tally_integrations.models.TallySyncLog.Direction",
        "TallySyncStatusEnum": "apps.tally_integrations.models.TallySyncLog.SyncStatus",
    },
}

# ---------------------------------------------------------------------------
# SimpleJWT
# ---------------------------------------------------------------------------
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173",
    cast=lambda v: [x.strip() for x in v.split(",")],
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "x-requested-with",
]

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

if TESTING:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# ---------------------------------------------------------------------------
# Localization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Test overrides (must come after all settings are defined)
# ---------------------------------------------------------------------------
if TESTING:
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
        k: None for k in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    }
