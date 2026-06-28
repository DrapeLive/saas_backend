from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_super_admin,
    create_user,
    get_jwt_headers,
)
from apps.accounts.views import CompanySetupViewSet
from apps.companies.models import CompanySettings


class CompanySetupTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile_view = CompanySetupViewSet.as_view({"patch": "update_profile"})
        self.bank_view = CompanySetupViewSet.as_view({"patch": "update_bank"})
        self.invoice_view = CompanySetupViewSet.as_view({"patch": "update_invoice"})
        self.tax_view = CompanySetupViewSet.as_view({"patch": "update_tax"})
        self.notifications_view = CompanySetupViewSet.as_view({"patch": "update_notifications"})

        self.company = create_company()
        self.admin = create_user(
            role=RoleType.ADMIN, company=self.company, email="admin@setup.com"
        )
        self.admin_headers = get_jwt_headers(self.admin)

        self.super_admin = create_super_admin()
        self.super_headers = get_jwt_headers(self.super_admin)

        self.agent = create_user(
            role=RoleType.AGENT, company=None, email="agent@setup.com"
        )
        self.agent_headers = get_jwt_headers(self.agent)

    def test_update_profile(self):
        response = self.profile_view(
            self.factory.patch(
                "/api/admin/setup/profile",
                {"name": "Updated Co", "gstin": "22AAAAA0000A1Z5"},
                format="json",
                **self.admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Updated Co")
        self.assertEqual(self.company.gstin, "22AAAAA0000A1Z5")

    def test_update_bank(self):
        response = self.bank_view(
            self.factory.patch(
                "/api/admin/setup/bank",
                {"bank_name": "SBI", "bank_account": "12345678901", "bank_ifsc": "SBIN0001234"},
                format="json",
                **self.admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.bank_name, "SBI")
        self.assertEqual(self.company.bank_account, "12345678901")

    def test_update_invoice(self):
        response = self.invoice_view(
            self.factory.patch(
                "/api/admin/setup/invoice",
                {"invoice_prefix": "INV-001"},
                format="json",
                **self.admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertEqual(self.company.invoice_prefix, "INV-001")

    def test_update_tax(self):
        settings, _ = CompanySettings.objects.get_or_create(company=self.company)
        response = self.tax_view(
            self.factory.patch(
                "/api/admin/setup/tax",
                {"default_gst_rate": "18.00", "reverse_charge": True},
                format="json",
                **self.admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings.refresh_from_db()
        self.assertEqual(float(settings.default_gst_rate), 18.00)
        self.assertTrue(settings.reverse_charge)

    def test_update_notifications_marks_completed(self):
        CompanySettings.objects.get_or_create(company=self.company)
        response = self.notifications_view(
            self.factory.patch(
                "/api/admin/setup/notifications",
                {"notify_order_whatsapp": False, "notify_order_email": False},
                format="json",
                **self.admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.company.refresh_from_db()
        self.assertTrue(self.company.setup_completed)

    def test_agent_cannot_access_setup(self):
        response = self.profile_view(
            self.factory.patch(
                "/api/admin/setup/profile",
                {"name": "Hacked"},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_cannot_access_setup(self):
        response = self.profile_view(
            self.factory.patch(
                "/api/admin/setup/profile",
                {"name": "Super Edit"},
                format="json",
                **self.super_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
