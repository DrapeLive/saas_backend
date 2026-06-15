from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

from apps.core.models import TimeStampedModel, UUIDModel


class RoleType(models.TextChoices):
    SUPER_ADMIN = "superadmin", "Super Admin"
    ADMIN = "admin", "Admin"
    SUB_ADMIN = "subadmin", "Sub Admin"
    AGENT = "agent", "Agent"
    CUSTOMER = "customer", "Customer"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", RoleType.SUPER_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel, TimeStampedModel):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=RoleType.choices)

    company = models.ForeignKey(
        "companies.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_device = models.CharField(max_length=200, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["role", "company"]),
            models.Index(fields=["email"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.role == RoleType.SUPER_ADMIN
            or self.role == RoleType.AGENT
            and self.company_id
        ):
            raise ValidationError("Super admin cannot belong to a company.")
        if self.role in (RoleType.ADMIN, RoleType.SUB_ADMIN) and not self.company_id:
            raise ValidationError(f"{self.role} must belong to a company.")

    def __str__(self):
        return f"{self.full_name} <{self.email}> [{self.role}]"

    @property
    def is_super_admin(self):
        return self.role == RoleType.SUPER_ADMIN

    @property
    def is_admin(self):
        return self.role == RoleType.ADMIN

    @property
    def is_sub_admin(self):
        return self.role == RoleType.SUB_ADMIN

    @property
    def is_agent(self):
        return self.role == RoleType.AGENT

    @property
    def is_customer(self):
        return self.role == RoleType.CUSTOMER


class AppModule(models.TextChoices):
    DASHBOARD = "dashboard", "Dashboard"
    CUSTOMERS = "customers", "Customers"
    PRODUCTS = "products", "Products"
    INVENTORY = "inventory", "Inventory"
    ORDERS = "orders", "Orders"
    DISPATCH = "dispatch", "Dispatch"
    INVOICING = "invoicing", "Invoicing"
    PAYMENTS = "payments", "Payments"
    COMMISSIONS = "commissions", "Commissions"
    AGENTS = "agents", "Agents"
    REPORTS = "reports", "Reports"
    TALLY_SYNC = "tally_sync", "Tally Sync"
    SETTINGS = "settings", "Settings"


class Permission(UUIDModel, TimeStampedModel):
    module = models.CharField(max_length=30, choices=AppModule.choices)
    can_view = models.BooleanField(default=False)
    can_add = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_permission"
        unique_together = [("module",)]

    def __str__(self):
        actions = [
            a
            for a, v in [
                ("View", self.can_view),
                ("Add", self.can_add),
                ("Edit", self.can_edit),
                ("Delete", self.can_delete),
                ("Export", self.can_export),
            ]
            if v
        ]
        return f"{self.module}: {', '.join(actions) or 'None'}"


class RoleTemplate(UUIDModel, TimeStampedModel):
    company = models.ForeignKey(
        "companies.Company",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="role_templates",
        help_text="Null = platform-wide default template",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    rank = models.PositiveSmallIntegerField(
        default=50,
        help_text="0–100; higher = more privilege. Prevents privilege escalation.",
    )
    is_default = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, blank=True)

    class Meta:
        db_table = "accounts_role_template"

    def __str__(self):
        return f"{self.name} (rank={self.rank})"


class SubAdminProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="subadmin_profile",
        limit_choices_to={"role": RoleType.SUB_ADMIN},
    )

    role_template = models.ForeignKey(
        RoleTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    custom_permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="subadmin_overrides",
    )

    restricted_agents = models.ManyToManyField(
        "agents.AgentProfile",
        blank=True,
        help_text="If set, SubAdmin can only see orders from these agents",
    )

    restricted_categories = models.ManyToManyField(
        "products.Category",
        blank=True,
        help_text="If set, SubAdmin can only manage these product categories",
    )

    approval_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Orders above this amount require Admin approval",
    )

    class Meta:
        db_table = "accounts_subadmin_profile"

    def __str__(self):
        return f"SubAdmin: {self.user.full_name}"
