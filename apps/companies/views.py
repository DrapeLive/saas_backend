from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import CanManageUsers, CompanyApproved, IsSuperAdmin
from apps.companies.models import Company
from apps.companies.serializers import (
    CompanyListSerializer,
    CompanySerializer,
    CompanyStatusUpdateSerializer,
)


class SuperAdminCompanyViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)

    def get_serializer_class(self):
        if self.action == "update_status":
            return CompanyStatusUpdateSerializer
        return CompanyListSerializer

    def list(self, request, *args, **kwargs):
        companies = Company.objects.all().order_by("-created_at")
        serializer = CompanyListSerializer(companies, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CompanySerializer(company)
        return Response(serializer.data)

    def update_status(self, request, pk=None, *args, **kwargs):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CompanyStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = company.status
        company.status = serializer.validated_data["status"]
        company.save(update_fields=["status"])

        return Response(
            {
                "detail": f"Company status changed from {old_status} to {company.status}.",
                "company": CompanySerializer(company).data,
            }
        )
