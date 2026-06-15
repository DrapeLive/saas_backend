from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleType, User
from apps.accounts.tests.factories import (
    create_company,
    create_super_admin,
    create_user,
    get_jwt_headers,
)
from apps.companies.models import CompanyStatus
from apps.companies.views import SuperAdminCompanyViewSet


class SuperAdminCompanyTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.list_view = SuperAdminCompanyViewSet.as_view({"get": "list"})
        self.retrieve_view = SuperAdminCompanyViewSet.as_view({"get": "retrieve"})
        self.status_view = SuperAdminCompanyViewSet.as_view({"post": "update_status"})

        self.company = create_company(
            status=CompanyStatus.PENDING,
        )
        self.company2 = create_company(
            name="Second Co", slug="second-co",
            contact_email="second@co.com",
            status=CompanyStatus.TRIAL,
        )
        self.super_admin = create_super_admin()
        self.super_headers = get_jwt_headers(self.super_admin)
        self.admin = create_user(
            role=RoleType.ADMIN, company=self.company, email="admin@test.com"
        )
        self.admin_headers = get_jwt_headers(self.admin)

    def test_list_all_companies(self):
        response = self.list_view(
            self.factory.get("/api/super-admin/companies", **self.super_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_retrieve_company(self):
        response = self.retrieve_view(
            self.factory.get(
                f"/api/super-admin/companies/{self.company.pk}",
                **self.super_headers,
            ),
            pk=self.company.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Company")
        self.assertEqual(response.data["status"], "pending")

    def test_update_status_pending_to_trial(self):
        response = self.status_view(
            self.factory.post(
                f"/api/super-admin/companies/{self.company.pk}/status",
                {"status": "trial"},
                format="json",
                **self.super_headers,
            ),
            pk=self.company.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "trial")

    def test_update_status_invalid_value(self):
        response = self.status_view(
            self.factory.post(
                f"/api/super-admin/companies/{self.company.pk}/status",
                {"status": "invalid"},
                format="json",
                **self.super_headers,
            ),
            pk=self.company.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_status_nonexistent_company(self):
        from uuid import uuid4
        response = self.status_view(
            self.factory.post(
                f"/api/super-admin/companies/{uuid4()}/status",
                {"status": "active"},
                format="json",
                **self.super_headers,
            ),
            pk=uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_nonexistent_company(self):
        from uuid import uuid4
        response = self.retrieve_view(
            self.factory.get(
                f"/api/super-admin/companies/{uuid4()}", **self.super_headers
            ),
            pk=uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_super_admin_only_gate(self):
        response = self.list_view(
            self.factory.get("/api/super-admin/companies", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        response = self.list_view(
            self.factory.get("/api/super-admin/companies")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
