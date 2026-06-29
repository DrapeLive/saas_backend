from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleType, User
from apps.agents.models import AgentCompanyMembership, AgentInvitation, AgentProfile
from apps.companies.models import Company


def create_company(**overrides):
    defaults = {
        "name": "Test Company",
        "slug": "test-company",
        "contact_email": "company@test.com",
        "contact_phone": "1234567890",
    }
    defaults.update(overrides)
    return Company.objects.create(**defaults)


def create_user(role=RoleType.ADMIN, company=None, **overrides):
    email = overrides.pop("email", f"{role}@test.com")
    password = overrides.pop("password", "Test@12345678")
    full_name = overrides.pop("full_name", f"{role.title()} User")
    phone = overrides.pop("phone", "1234567890")

    defaults = {
        "email": email,
        "password": password,
        "full_name": full_name,
        "phone": phone,
        "role": role,
        "company": company,
    }
    defaults.update(overrides)
    user = User.objects.create_user(**defaults)
    return user


def create_super_admin(**overrides):
    overrides.setdefault("email", "super@admin.com")
    overrides.setdefault("full_name", "Super Admin")
    return create_user(role=RoleType.SUPER_ADMIN, company=None, **overrides)


def create_agent_profile(user):
    return AgentProfile.objects.get_or_create(user=user)[0]


def create_membership(agent_profile, company, status="active"):
    return AgentCompanyMembership.objects.create(
        agent=agent_profile,
        company=company,
        status=status,
    )


def create_invitation(company, invited_by, **overrides):
    from django.utils import timezone
    import secrets

    defaults = {
        "email": "agent@invite.com",
        "phone": "",
        "token": secrets.token_urlsafe(32),
        "delivery_method": "email",
        "expires_at": timezone.now() + timezone.timedelta(days=7),
    }
    defaults.update(overrides)
    return AgentInvitation.objects.create(
        company=company,
        invited_by=invited_by,
        **defaults,
    )


def create_customer(company, **overrides):
    from apps.customers.models import CustomerProfile

    defaults = {
        "trade_name": "Test Customer",
        "phone": "9876543210",
        "email": "customer@test.com",
        "owner_name": "Owner Name",
    }
    defaults.update(overrides)
    return CustomerProfile.objects.create(company=company, **defaults)


def get_jwt_headers(user):
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["company_id"] = str(user.company_id) if user.company_id else None
    refresh["is_super_admin"] = user.role == RoleType.SUPER_ADMIN
    return {
        "HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}",
    }
