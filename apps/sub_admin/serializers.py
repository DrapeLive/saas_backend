from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import Permission, RoleTemplate, RoleType, SubAdminProfile, User
from apps.accounts.serializers import PermissionSerializer
from apps.agents.models import AgentProfile
from apps.products.models import Category


class RoleTemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    rank = serializers.IntegerField(min_value=0, max_value=100, required=False, default=50)
    is_default = serializers.BooleanField(required=False, default=False)
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True
    )

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
        permission_ids = validated_data.pop("permission_ids", [])
        is_default = validated_data.pop("is_default", False)
        template = RoleTemplate.objects.create(
            company=company,
            is_default=is_default,
            **validated_data,
        )
        if permission_ids:
            template.permissions.set(Permission.objects.filter(pk__in=permission_ids))
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
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True
    )

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
        permission_ids = validated_data.pop("permission_ids", None)
        is_default = validated_data.get("is_default")

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if permission_ids is not None:
            instance.permissions.set(
                Permission.objects.filter(pk__in=permission_ids)
            )

        if is_default:
            RoleTemplate.objects.filter(
                company=company, is_default=True
            ).exclude(pk=instance.pk).update(is_default=False)

        return instance


class RoleTemplateDetailSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SubAdminCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    role_template_id = serializers.UUIDField(required=False, allow_null=True)
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
        approval_threshold = validated_data.pop("approval_threshold", None)
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
        if role_template is not None:
            profile.role_template = role_template
        if approval_threshold is not None:
            profile.approval_threshold = approval_threshold
        profile.save()
        return profile


class SubAdminUpdateSerializer(serializers.ModelSerializer):
    role_template_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = SubAdminProfile
        fields = ["approval_threshold", "role_template_id"]

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
        role_template_id = validated_data.pop("role_template_id", None)
        profile = super().update(instance, validated_data)
        if role_template_id is not None:
            from apps.accounts.models import RoleTemplate

            profile.role_template = RoleTemplate.objects.get(pk=role_template_id)
            profile.save(update_fields=["role_template", "updated_at"])
        return profile


class SubAdminDetailSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="user.id")
    email = serializers.EmailField(source="user.email")
    full_name = serializers.CharField(source="user.full_name")
    phone = serializers.CharField(source="user.phone")
    is_active = serializers.BooleanField(source="user.is_active")
    company = serializers.UUIDField(source="user.company_id")
    role_template = serializers.PrimaryKeyRelatedField(read_only=True)
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
            "restricted_agents",
            "restricted_categories",
            "approval_threshold",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


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