# SaaS Backend — Developer Reference

## Tech Stack

- **Python** 3.12, **Django** 5.2, **PostgreSQL** (Supabase)
- **DRF** 3.17 + **SimpleJWT** 5.5 — REST API + JWT auth
- **django-cors-headers** for CORS

## Auth Architecture

### Multi-Tenant Model

Users belong to companies via `User.company` FK (nullable). Agents additionally use `AgentCompanyMembership` to join multiple companies.

| Role | Company FK | Notes |
|------|-----------|-------|
| `superadmin` | `null` | Platform-wide, created via `createsuperuser` |
| `admin` | Required | Created during signup or by super admin |
| `subadmin` | Required | Created by company admin |
| `agent` | `null` | Self-registers, joins companies via invite code |
| `customer` | TBD | Future |

### Auth Flow

```
POST /api/auth/signup/         → Creates Company(status=PENDING) + Admin user
                                     ← Returns JWT pair (access + refresh)
POST /api/auth/login/          → Authenticate, returns JWT pair
POST /api/auth/refresh/        → Rotate refresh token, return new pair
POST /api/auth/logout/         → Blacklist refresh token
POST /api/auth/password/change/
POST /api/auth/password/reset/
POST /api/auth/password/reset/confirm/
GET|PATCH /api/auth/me/

POST /api/auth/agents/register/  → Agent self-registration
POST /api/auth/agents/join/      → Agent joins company via invite code
```

### Company Lifecycle

1. **PENDING** — Signup complete, awaiting super admin approval. Admin can log in but cannot access business features.
2. **TRIAL** — Approved by super admin. 14-day trial active.
3. **ACTIVE** — Paid subscription.
4. **SUSPENDED / EXPIRED / GRACE** — Disabled or expiring.

Super admin updates status via `POST /api/super-admin/companies/{id}/status`.

### Token Strategy

- **Access token**: 24 hours
- **Refresh token**: 30 days, rotated on each refresh
- **Blacklist**: DB-backed (SimpleJWT `token_blacklist`). Tokens blacklisted on logout or by super admin.
- **JWT claims**: `user_id`, `role`, `company_id`, `is_super_admin`

## Permissions (DRF)

| Class | Grants access to |
|-------|-----------------|
| `IsSuperAdmin` | `role == superadmin` only |
| `IsCompanyAdmin` | `role == admin` with a company |
| `IsCompanyAdminOrAbove` | `superadmin` or `admin` |
| `IsCompanyStaff` | Any company user (admin, subadmin, agent) |
| `IsAgent` | `role == agent` only |
| `CompanyApproved` | Blocks access if company.status == PENDING (bypasses for superadmin) |
| `CanManageUsers` | `superadmin` or `admin` |

## Multi-Tenant Data Isolation

- `CustomJWTAuthentication` sets `request.company` from JWT claims after authentication.
- `CompanyScopeMiddleware` initializes `request.company = None` for unauthenticated requests.
- Company-scoped models inherit from `CompanyScopeModel` (in `apps.core.models`).
- Super admins bypass all company scoping.

## Key Files

| File | Purpose |
|------|---------|
| `apps/accounts/authentication.py` | Custom JWT auth + company scoping |
| `apps/accounts/permissions.py` | DRF permission classes |
| `apps/accounts/serializers.py` | All auth serializers |
| `apps/accounts/views.py` | LoginView, SignupView, AuthViewSet, AdminUserViewSet, InvitationViewSet, AdminDashboardViewSet, AdminAnalyticsViewSet, SuperAdminDashboardViewSet |
| `apps/accounts/urls.py` | All `/api/*` routes |
| `apps/accounts/middleware.py` | CompanyScopeMiddleware |
| `apps/companies/serializers.py` | Company serializers |
| `apps/companies/views.py` | SuperAdminCompanyViewSet |
| `apps/companies/urls.py` | `/api/super-admin/*` routes |
| `config/settings.py` | DRF, JWT, CORS, throttle config |

## Complete API Endpoints

### Public — `/api/auth/*`
| Method | Path | Auth | Perm |
|--------|------|------|------|
| POST | `/api/auth/signup` | — | AllowAny |
| POST | `/api/auth/login` | — | AllowAny |
| POST | `/api/auth/refresh` | — | AllowAny (valid refresh) |
| POST | `/api/auth/logout` | Bearer | IsAuthenticated |
| POST | `/api/auth/password/change` | Bearer | IsAuthenticated |
| POST | `/api/auth/password/reset` | — | AllowAny |
| POST | `/api/auth/password/reset/confirm` | — | AllowAny |
| GET/PATCH | `/api/auth/me` | Bearer | IsAuthenticated |
| POST | `/api/auth/agents/register` | — | AllowAny |
| POST | `/api/auth/agents/join` | Bearer | IsAuthenticated + IsAgent |

### Company Admin — `/api/admin/*`
| Method | Path | Auth | Perm |
|--------|------|------|------|
| GET | `/api/admin/users` | Bearer | CanManageUsers + CompanyApproved |
| POST | `/api/admin/users` | Bearer | CanManageUsers + CompanyApproved |
| PATCH | `/api/admin/users/<uuid:pk>` | Bearer | CanManageUsers + CompanyApproved |
| DELETE | `/api/admin/users/<uuid:pk>` | Bearer | CanManageUsers + CompanyApproved |
| GET | `/api/admin/invitations` | Bearer | IsCompanyAdmin + CompanyApproved |
| POST | `/api/admin/invitations` | Bearer | IsCompanyAdmin + CompanyApproved |
| GET | `/api/admin/dashboard` | Bearer | IsCompanyAdminOrAbove + CompanyApproved |
| GET | `/api/admin/analytics` | Bearer | IsCompanyAdminOrAbove + CompanyApproved |

### Super Admin — `/api/super-admin/*`
| Method | Path | Auth | Perm |
|--------|------|------|------|
| GET | `/api/super-admin/companies` | Bearer | IsSuperAdmin |
| GET | `/api/super-admin/companies/<uuid:pk>` | Bearer | IsSuperAdmin |
| POST | `/api/super-admin/companies/<uuid:pk>/status` | Bearer | IsSuperAdmin |
| GET | `/api/super-admin/dashboard` | Bearer | IsSuperAdmin |

## Dashboard KPIs

### Super Admin Dashboard — `GET /api/super-admin/dashboard`
| KPI | Source |
|-----|--------|
| `total_companies` | `Company.objects.count()` |
| `active_companies` | `Company.objects.filter(status='active').count()` |
| `trial_companies` | `Company.objects.filter(status='trial').count()` |
| `expired_companies` | `Company.objects.filter(status='expired').count()` |
| `mrr` | `SUM(price_paid / billing_cycle_months)` for active subscriptions |
| `arr` | `MRR × 12` |
| `churn_rate` | Churned this month / total companies at month start |
| `ltv` | `AVG(price_paid)` across non-trial subscriptions |

### Admin Dashboard — `GET /api/admin/dashboard`
| KPI | Source |
|-----|--------|
| `orders_today` | Count of orders submitted today |
| `sales_today` | `SUM(total_amount)` for confirmed/dispatched/delivered today |
| `outstanding_total` | `SUM(amount_due)` on issued/partial/overdue invoices |
| `overdue_total` | `SUM(amount_due)` on past-due invoices |
| `avg_order_value` | Rolling 30-day average of `total_amount` |
| `agent_response_time` | Avg hours from `submitted_at` to `confirmed_at` |
| `order_conversion_rate` | Confirmed / submitted orders this month |

### Admin Analytics — `GET /api/admin/analytics`
| Chart | Data |
|-------|------|
| Sales trend | Line chart, truncated by month (12 months) |
| Top products by revenue | Bar chart, top 10 by `line_total` |
| Agent comparison | Bar chart, MTD sales per agent |
| Outstanding aging | Stacked bar: current, 31–60, 61–90, 90+ days |
| Customer acquisition funnel | Total customers vs. customers with orders |

## Rate Limiting (DRF Throttling)

| Scope | Limit |
|-------|-------|
| `anon` | 20/min |
| `user` | 100/min |
| `login` | 5/min |
| `signup` | 3/min |
| `password_reset` | 3/hour |

## Testing Philosophy

- **Tests are the source of truth.** When a test fails, the application code must be fixed — never rewrite a passing test to match buggy behavior.
- All auth/business logic must have test coverage before being considered complete.
- Run tests before every commit: `python manage.py test apps.accounts.tests --verbosity=2`
- Use `apps.accounts.tests.factories` helpers for DRY, consistent test setup.
- Tests use SQLite in-memory (configured automatically via `TESTING` flag in `settings.py`). Throttling is disabled during tests.

## Configuration (`.env`)

```
DATABASE_URL=postgresql://...
SECRET_KEY=...
DEBUG=True
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
```

## Bruno API Client

### File Structure

```
bruno/
  environments/                    # Environment YAML files
    admin.yml                      # Admin env: base_url, login_email, login_password, auth_token
    superadmin.yml                 # Super admin env: same vars, different credentials
  collections/
    auth/
      bruno.json                   # Auth collection root
      Login.bru                    # POST login → post-response extracts access token → auth_token
      Signup.bru                   # POST signup (no auth, hardcoded test data)
    admin/
      bruno.json                   # Admin collection root
      Analytics.bru                # GET /api/admin/analytics
      Dashboard.bru                # GET /api/admin/dashboard
      Setup Bank.bru               # PATCH /api/admin/setup/bank
      Setup Invoice.bru            # PATCH /api/admin/setup/invoice
      Setup Notifications.bru      # PATCH /api/admin/setup/notifications
      Setup Profile.bru            # PATCH /api/admin/setup/profile
      Setup Tax.bru                # PATCH /api/admin/setup/tax
    super-admin/
      bruno.json                   # Super admin collection root
      Activate Company.bru         # POST /api/super-admin/companies/{{company_id}}/activate
      Dashboard.bru                # GET /api/super-admin/dashboard
      Delete Company.bru           # DELETE /api/super-admin/companies/{{company_id}}
      Extend Trial.bru             # POST /api/super-admin/companies/{{company_id}}/extend-trial
      Get Company.bru              # GET /api/super-admin/companies/{{company_id}}
      Impersonate Company.bru      # POST /api/super-admin/companies/{{company_id}}/impersonate
      List Companies.bru           # GET /api/super-admin/companies
      Suspend Company.bru          # POST /api/super-admin/companies/{{company_id}}/suspend
      Update Status.bru            # POST /api/super-admin/companies/{{company_id}}/status
```

### Auth Flow (Token Chaining)

1. Two environments — **admin** and **superadmin** — each with env vars: `base_url`, `login_email`, `login_password`, `auth_token` (initially empty).
2. Import the `.yml` file from `bruno/environments/` into Bruno's environment manager, then select it from the dropdown.
3. Run **Login** with the desired environment selected. The post-response script extracts `body.access` (JWT access token) and saves it into `auth_token` for the session.
4. All other requests reference `auth:bearer { token: {{auth_token}} }` — no hardcoded tokens.
5. Switch environments to test the other role — each has its own independent `auth_token`.

### Response Key

Login response returns `access` as the JWT token key. Script uses `JSON.parse(res.getBody())` since `.bru` format returns raw JSON string.

### Bruno Format

Requests use `.bru` format. Environments use `.yml` format (Bruno native for env files).

## Adding Auth to New Endpoints

```python
from rest_framework.viewsets import GenericViewSet
from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsCompanyStaff, CompanyApproved

class MyViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsCompanyStaff)

    def list(self, request, ...):
        # request.user — authenticated user
        # request.company — user's company (None for superadmin/agents without membership)
        queryset = MyModel.objects.filter(company=request.company)
        ...
```
