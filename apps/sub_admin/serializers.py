from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import (
    AppModule,
    Permission,
    RoleTemplate,
    RoleType,
    SubAdminProfile,
    User,
)
from apps.agents.models import AgentProfile
from apps.products.models import Category
from apps.sub_admin.services import (
    get_effective_permission_map,
    revoke_user_refresh_tokens,
    serialize_module_permissions,
    set_subadmin_permissions,
    set_template_permissions,
)


def _validate_permission_rows(value):
    """Validate and normalize a list of module permission dicts."""
    valid_modules = set(AppModule.values)
    normalized = {}
    for item in value:
        if not isinstance(item, dict):
            raise serializers.ValidationError(
                "Each permission entry must be an object."
            )
        module = str(item.get("module", "")).strip()
        if module not in valid_modules:
            raise serializers.ValidationError(f"Unknown module: {module!r}.")
        normalized[module] = {
            "module": module,
            "can_view": bool(item.get("can_view", False)),
            "can_add": bool(item.get("can_add", False)),
            "can_edit": bool(item.get("can_edit", False)),
            "can_delete": bool(item.get("can_delete", False)),
            "can_export": bool(item.get("can_export", False)),
        }
    return list(normalized.values())


def _rows_from_permission_ids(permission_ids):
    """Legacy support: a selected module means view access."""
    rows = []
    for permission in Permission.objects.filter(pk__in=permission_ids):
        rows.append({"module": permission.module, "can_view": True})
    return rows


class ModulePermissionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    module = serializers.CharField()
    can_view = serializers.BooleanField()
    can_add = serializers.BooleanField()
    can_edit = serializers.BooleanField()
    can_delete = serializers.BooleanField()
    can_export = serializers.BooleanField()


class RoleTemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    rank = serializers.IntegerField(min_value=0, max_value=100, required=False, default=50)
    is_default = serializers.BooleanField(required=False, default=False)
    permissions = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True
    )

    def validate_permissions(self, value):
        return _validate_permission_rows(value)

    def validate_permission_ids(self, value):
        existing = set(Permission.objects.filter(pk__in=value).values_list("id", flat=True))
        missing = [str(pk) for pk in value if pk not in existing]
        if missing:
            raise serializers.ValidationError(
                f"Permissions do not exist: {missing}"
            )
        return value

    def create(self, validated_data):
        company = self.context["company"]
        permissions = validated_data.pop("permissions", None)
        permission_ids = validated_data.pop("permission_ids", [])
        is_default = validated_data.pop("is_default", False)
        template = RoleTemplate.objects.create(
            company=company,
            is_default=is_default,
            **validated_data,
        )
        rows = permissions
        if rows is None and permission_ids:
            rows = _rows_from_permission_ids(permission_ids)
        if rows:
            set_template_permissions(template, rows)
        if is_default:
            RoleTemplate.objects.filter(
                company=company, is_default=True
            ).exclude(pk=template.pk).update(is_default=False)
        return template


class RoleTemplateUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    rank = serializers.IntegerField(min_value=0, max_value=100, required=False)
    is_default = serializers.BooleanField(required=False)
    permissions = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True
    )

    def validate_permissions(self, value):
        return _validate_permission_rows(value)

    def validate_permission_ids(self, value):
        existing = set(Permission.objects.filter(pk__in=value).values_list("id", flat=True))
        missing = [str(pk) for pk in value if pk not in existing]
        if missing:
            raise serializers.ValidationError(
                f"Permissions do not exist: {missing}"
            )
        return value

    def update(self, instance, validated_data):
        company = self.context.get("company")
        permissions = validated_data.pop("permissions", None)
        permission_ids = validated_data.pop("permission_ids", None)
        is_default = validated_data.get("is_default")

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        rows = permissions
        if rows is None and permission_ids is not None:
            rows = _rows_from_permission_ids(permission_ids)
        if rows is not None:
            set_template_permissions(instance, rows)

        if is_default:
            RoleTemplate.objects.filter(
                company=company, is_default=True
            ).exclude(pk=instance.pk).update(is_default=False)

        return instance


class RoleTemplateDetailSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    permission_ids = serializers.SerializerMethodField()

    class Meta:
        model = RoleTemplate
        fields = [
            "id",
            "name",
            "description",
            "rank",
            "is_default",
            "company",
            "permissions",
            "permission_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_permissions(self, obj):
        return serialize_module_permissions(obj.module_permissions.all())

    def get_permission_ids(self, obj):
        """Legacy field: ids of the module rules selected by this template."""
        return [str(rule.id) for rule in obj.module_permissions.all()]


class SubAdminCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    role_template_id = serializers.UUIDField(required=False, allow_null=True)
    permissions = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    approval_threshold = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return value.lower()

    def validate_permissions(self, value):
        return _validate_permission_rows(value)

    def validate_role_template_id(self, value):
        if value is None:
            return None
        from apps.accounts.models import RoleTemplate

        try:
            template = RoleTemplate.objects.get(pk=value)
        except RoleTemplate.DoesNotExist:
            raise serializers.ValidationError("Role template does not exist.")
        company = self.context.get("company")
        if company is not None and template.company_id not in (None, company.id):
            raise serializers.ValidationError(
                "Role template does not belong to this company."
            )
        return template

    def create(self, validated_data):
        company = self.context["company"]
        role_template = validated_data.pop("role_template_id", None)
        permissions = validated_data.pop("permissions", None)
        approval_threshold = validated_data.pop("approval_threshold", None)

        if role_template is None:
            role_template = RoleTemplate.objects.filter(
                company=company, is_default=True
            ).first()

        user = User.objects.create_user(
            role=RoleType.SUB_ADMIN,
            company=company,
            **validated_data,
        )
        profile, _ = SubAdminProfile.objects.get_or_create(
            user=user,
            defaults={
                "role_template": role_template,
                "approval_threshold": approval_threshold,
            },
        )
        profile.role_template = role_template
        if approval_threshold is not None:
            profile.approval_threshold = approval_threshold
        profile.save()

        if permissions is not None:
            set_subadmin_permissions(profile, permissions)
        return profile


class SubAdminUpdateSerializer(serializers.ModelSerializer):
    role_template_id = serializers.UUIDField(required=False, allow_null=True)
    permissions = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    is_active = serializers.BooleanField(required=False)

    class Meta:
        model = SubAdminProfile
        fields = ["approval_threshold", "role_template_id", "permissions", "is_active"]

    def validate_permissions(self, value):
        return _validate_permission_rows(value)

    def validate_role_template_id(self, value):
        if value is None:
            return None
        from apps.accounts.models import RoleTemplate

        try:
            template = RoleTemplate.objects.get(pk=value)
        except RoleTemplate.DoesNotExist:
            raise serializers.ValidationError("Role template does not exist.")
        company = self.context.get("company")
        if company is not None and template.company_id not in (None, company.id):
            raise serializers.ValidationError(
                "Role template does not belong to this company."
            )
        return template

    def update(self, instance, validated_data):
        permissions = validated_data.pop("permissions", None)
        is_active = validated_data.pop("is_active", None)
        has_template = "role_template_id" in validated_data
        role_template = validated_data.pop("role_template_id", None)

        profile = super().update(instance, validated_data)

        if has_template:
            profile.role_template = role_template
            profile.save(update_fields=["role_template", "updated_at"])

        if permissions is not None:
            set_subadmin_permissions(profile, permissions)
        elif has_template:
            # Switching template resets explicit overrides so the new
            # template's defaults take effect immediately.
            profile.module_permissions.all().delete()

        if is_active is not None:
            profile.user.is_active = is_active
            profile.user.save(update_fields=["is_active"])
            if not is_active:
                revoke_user_refresh_tokens(profile.user)

        return profile


class SubAdminDetailSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="user.id")
    email = serializers.EmailField(source="user.email")
    full_name = serializers.CharField(source="user.full_name")
    phone = serializers.CharField(source="user.phone")
    is_active = serializers.BooleanField(source="user.is_active")
    company = serializers.UUIDField(source="user.company_id")
    role_template = serializers.PrimaryKeyRelatedField(read_only=True)
    permissions = serializers.SerializerMethodField()
    restricted_agents = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True
    )
    restricted_categories = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True
    )
    approval_threshold = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )

    class Meta:
        model = SubAdminProfile
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "is_active",
            "company",
            "role_template",
            "permissions",
            "restricted_agents",
            "restricted_categories",
            "approval_threshold",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_permissions(self, obj):
        return get_effective_permission_map(obj.user)


class SubAdminListSerializer(SubAdminDetailSerializer):
    pass


class RestrictAgentsSerializer(serializers.Serializer):
    agent_ids = serializers.ListField(child=serializers.UUIDField())

    def validate_agent_ids(self, value):
        company = self.context.get("company")
        agents = AgentProfile.objects.filter(memberships__company=company)
        existing = set(agents.values_list("id", flat=True))
        invalid = [str(a) for a in value if a not in existing]
        if invalid:
            raise serializers.ValidationError(
                f"Agents not in this company: {invalid}"
            )
        return value


class RestrictCategoriesSerializer(serializers.Serializer):
    category_ids = serializers.ListField(child=serializers.UUIDField())

    def validate_category_ids(self, value):
        company = self.context.get("company")
        categories = Category.objects.filter(company=company)
        existing = set(categories.values_list("id", flat=True))
        invalid = [str(c) for c in value if c not in existing]
        if invalid:
            raise serializers.ValidationError(
                f"Categories not in this company: {invalid}"
            )
        return value
