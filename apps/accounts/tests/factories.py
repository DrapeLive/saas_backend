from rest_framework_simplejwt.tokens import RefreshToken

from apps.companies.models import Company
from apps.customers.models import CustomerProfile
from apps.accounts.models import RoleType, User


def create_company(
    name="Acme Textiles",
    slug=None,
    status="trial",
    **extra,
) -> Company:
    slug = slug or f"{name.lower().replace(' ', '-')}-{Company.objects.count() + 1}"
    return Company.objects.create(
        name=name,
        slug=slug,
        contact_email=f"ops@{slug}.com",
        contact_phone="9876543210",
        status=status,
        **extra,
    )


def create_user(
    email=None,
    role=RoleType.ADMIN,
    company=None,
    password="pass-12345",
    **extra,
) -> User:
    email = email or f"{role}.{User.objects.count() + 1}@example.com"
    return User.objects.create_user(
        email=email,
        password=password,
        full_name=extra.pop("full_name", email.split("@")[0].title()),
        role=role,
        company=company,
        **extra,
    )


def create_super_admin(email=None, **extra) -> User:
    return create_user(
        email=email or "superadmin@example.com",
        role=RoleType.SUPER_ADMIN,
        company=None,
        **extra,
    )


def create_customer(
    company: Company, trade_name="Fashion Hub", phone="9123456780", **extra
) -> CustomerProfile:
    return CustomerProfile.objects.create(
        company=company,
        trade_name=trade_name,
        legal_name=extra.pop("legal_name", f"{trade_name} Pvt Ltd"),
        phone=phone,
        **extra,
    )


def get_jwt_headers(user: User) -> dict:
    """Auth headers carrying a real JWT (with company claim when applicable)."""
    refresh = RefreshToken.for_user(user)
    if user.company_id:
        refresh["company_id"] = str(user.company_id)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}
