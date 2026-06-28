from rest_framework import serializers

from apps.companies.models import Company


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        exclude = ["impersonation_token"]


class CompanyListSerializer(serializers.ModelSerializer):
    admin_email = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "contact_email",
            "contact_phone",
            "admin_email",
            "admin_name",
            "created_at",
        ]

    def get_admin_email(self, obj):
        admin = obj.members.filter(role="admin").first()
        return admin.email if admin else None

    def get_admin_name(self, obj):
        admin = obj.members.filter(role="admin").first()
        return admin.full_name if admin else None


class CompanyStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            "pending",
            "trial",
            "active",
            "suspended",
            "expired",
            "grace",
        ]
    )


class ExtendTrialSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=90)
    reason = serializers.CharField(max_length=500)
