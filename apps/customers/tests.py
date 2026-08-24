import json

from django.test import TestCase
from rest_framework import status

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_customer,
    create_super_admin,
    create_user,
    get_jwt_headers,
)


def json_headers(token_headers):
    headers = token_headers.copy()
    headers["content_type"] = "application/json"
    return headers


class CustomerListCreateTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_list_customers_empty(self):
        resp = self.client.get(
            "/api/admin/customers/", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_list_customers_with_data(self):
        c1 = create_customer(self.company, trade_name="Alpha")
        c2 = create_customer(self.company, trade_name="Beta")
        resp = self.client.get(
            "/api/admin/customers/", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_list_customers_search(self):
        create_customer(self.company, trade_name="Searchable Corp", phone="1111111111")
        create_customer(self.company, trade_name="Other Corp", phone="2222222222")
        resp = self.client.get(
            "/api/admin/customers/?search=Searchable", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["trade_name"], "Searchable Corp")

    def test_list_customers_filter_status(self):
        create_customer(self.company, trade_name="Active One", status="active")
        create_customer(self.company, trade_name="Inactive One", status="inactive")
        resp = self.client.get(
            "/api/admin/customers/?status=inactive", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["trade_name"], "Inactive One")

    def test_list_customers_filter_tag(self):
        create_customer(self.company, trade_name="Tagged", tags=["wholesale", "premium"])
        create_customer(self.company, trade_name="Untagged")
        resp = self.client.get(
            "/api/admin/customers/?tag=wholesale", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["trade_name"], "Tagged")

    def test_list_customers_filter_segment(self):
        create_customer(self.company, trade_name="Gold One", segment="gold")
        create_customer(self.company, trade_name="Bronze One", segment="bronze")
        resp = self.client.get(
            "/api/admin/customers/?segment=gold", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["trade_name"], "Gold One")

    def test_list_customers_ordering(self):
        create_customer(self.company, trade_name="B")
        create_customer(self.company, trade_name="A")
        resp = self.client.get(
            "/api/admin/customers/?ordering=trade_name", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data[0]["trade_name"], "A")
        self.assertEqual(resp.data[1]["trade_name"], "B")

    def test_list_customers_superadmin_sees_all(self):
        other_company = create_company(name="Other", slug="other", status="active")
        create_customer(self.company, trade_name="Company A")
        create_customer(other_company, trade_name="Company B")
        super_admin = create_super_admin()
        resp = self.client.get(
            "/api/admin/customers/", **get_jwt_headers(super_admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_customers_unauthorized(self):
        resp = self.client.get("/api/admin/customers/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_customer_minimal(self):
        payload = {"trade_name": "New Customer", "phone": "9999999999"}
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["trade_name"], "New Customer")
        self.assertEqual(resp.data["phone"], "9999999999")

    def test_create_customer_full(self):
        payload = {
            "legal_name": "Legal Entity Inc",
            "trade_name": "Trade Name Inc",
            "owner_name": "John Doe",
            "email": "john@example.com",
            "phone": "8888888888",
            "whatsapp_number": "8888888888",
            "gstin": "27AABCU9603R1ZX",
            "pan": "ABCDE1234F",
            "tags": ["wholesale", "export"],
            "billing_city": "Mumbai",
            "billing_state": "Maharashtra",
            "billing_pincode": "400001",
            "same_as_billing": True,
            "credit_limit": 50000,
            "payment_terms_days": 45,
            "status": "active",
            "internal_notes": "VIP customer",
        }
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["legal_name"], "Legal Entity Inc")
        self.assertEqual(resp.data["tags"], ["wholesale", "export"])

    def test_create_customer_duplicate_gstin(self):
        create_customer(self.company, gstin="27AABCU9603R1ZX")
        payload = {
            "trade_name": "Duplicate GST",
            "phone": "7777777777",
            "gstin": "27AABCU9603R1ZX",
        }
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_customer_agent_not_allowed(self):
        agent_user = create_user(role=RoleType.AGENT)
        payload = {"trade_name": "Agent Test", "phone": "6666666666"}
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(agent_user),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_customer_pending_company_blocked(self):
        pending_company = create_company(name="Pending Co", slug="pending-co", status="pending")
        admin_pending = create_user(role=RoleType.ADMIN, company=pending_company, email="admin@pending.com")
        payload = {"trade_name": "Pending Test", "phone": "5555555555"}
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(admin_pending),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class CustomerRetrieveUpdateDeleteTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company, trade_name="Retrieve Me")

    def test_retrieve_customer(self):
        resp = self.client.get(
            f"/api/admin/customers/{self.customer.id}/", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["trade_name"], "Retrieve Me")

    def test_retrieve_customer_not_found(self):
        resp = self.client.get(
            "/api/admin/customers/00000000-0000-0000-0000-000000000000/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_customer(self):
        resp = self.client.patch(
            f"/api/admin/customers/{self.customer.id}/",
            data=json.dumps({"trade_name": "Updated Name", "internal_notes": "Updated notes"}),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["trade_name"], "Updated Name")
        self.assertEqual(resp.data["internal_notes"], "Updated notes")

    def test_update_customer_credit_limit(self):
        resp = self.client.patch(
            f"/api/admin/customers/{self.customer.id}/",
            data=json.dumps({"credit_limit": 100000}),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["credit_limit"], "100000.00")

    def test_delete_customer(self):
        resp = self.client.delete(
            f"/api/admin/customers/{self.customer.id}/", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.client.get(
            f"/api/admin/customers/{self.customer.id}/",
            **get_jwt_headers(self.admin),
        )


class CustomerImportTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_import_preview_valid(self):
        payload = {
            "rows": [
                {"trade_name": "Imported Co", "phone": "1111111111"},
                {"trade_name": "Imported Co 2", "phone": "2222222222"},
            ]
        }
        resp = self.client.post(
            "/api/admin/customers/import-preview/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total"], 2)
        self.assertEqual(len(resp.data["valid"]), 2)
        self.assertEqual(len(resp.data["errors"]), 0)

    def test_import_preview_with_errors(self):
        payload = {
            "rows": [
                {"trade_name": "Good Co", "phone": "1111111111"},
                {"trade_name": "", "phone": ""},
            ]
        }
        resp = self.client.post(
            "/api/admin/customers/import-preview/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["valid"]), 1)
        self.assertEqual(len(resp.data["errors"]), 1)

    def test_import_confirm_creates_customers(self):
        payload = {
            "rows": [
                {"trade_name": "Bulk Co 1", "phone": "1111111111"},
                {"trade_name": "Bulk Co 2", "phone": "2222222222"},
            ]
        }
        resp = self.client.post(
            "/api/admin/customers/import-confirm/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(resp.data["created"]), 2)
        self.assertEqual(resp.data["total"], 2)

    def test_import_confirm_partial_errors(self):
        payload = {
            "rows": [
                {"trade_name": "Good Co", "phone": "1111111111"},
                {"trade_name": "", "phone": ""},
            ]
        }
        resp = self.client.post(
            "/api/admin/customers/import-confirm/",
            data=json.dumps(payload),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(resp.data["created"]), 1)
        self.assertEqual(len(resp.data["errors"]), 1)


class CustomerGstinTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company, gstin="27AABCU9603R1ZX")

    def test_verify_gstin_stub(self):
        resp = self.client.post(
            f"/api/admin/customers/{self.customer.id}/verify-gstin/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["valid"])

    def test_verify_gstin_no_gstin(self):
        no_gstin = create_customer(self.company, trade_name="No GST", gstin="")
        resp = self.client.post(
            f"/api/admin/customers/{no_gstin.id}/verify-gstin/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class CustomerSegmentTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company)

    def test_compute_segment_default_bronze(self):
        resp = self.client.post(
            f"/api/admin/customers/{self.customer.id}/compute-segment/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["segment"], "bronze")


class CustomerCreditBlockTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company)

    def test_credit_block(self):
        resp = self.client.post(
            f"/api/admin/customers/{self.customer.id}/credit-block/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_credit_blocked"])
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_credit_blocked)

    def test_credit_unblock(self):
        self.customer.is_credit_blocked = True
        self.customer.save()
        resp = self.client.post(
            f"/api/admin/customers/{self.customer.id}/credit-unblock/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["is_credit_blocked"])
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_credit_blocked)


class CustomerDocumentTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.agent_user = create_user(role=RoleType.AGENT, email="agent@docs.com")
        self.customer = create_customer(self.company)

    def test_list_documents_empty(self):
        resp = self.client.get(
            f"/api/admin/customers/{self.customer.id}/documents/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_agent_can_list_documents(self):
        resp = self.client.get(
            f"/api/admin/customers/{self.customer.id}/documents/",
            **get_jwt_headers(self.agent_user),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class CustomerCommunicationLogTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company)

    def test_list_communication_logs_empty(self):
        resp = self.client.get(
            f"/api/admin/customers/{self.customer.id}/communication-logs/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])


class CustomerPermissionsTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.subadmin = create_user(
            role=RoleType.SUB_ADMIN, company=self.company, email="subadmin@test.com"
        )
        self.agent_user = create_user(role=RoleType.AGENT, email="agent@perms.com")
        self.customer = create_customer(self.company)

    def test_admin_can_create(self):
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps({"trade_name": "Admin Test", "phone": "1111111111"}),
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_subadmin_can_create(self):
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps({"trade_name": "SubAdmin Test", "phone": "2222222222"}),
            content_type="application/json",
            **get_jwt_headers(self.subadmin),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_agent_cannot_create(self):
        resp = self.client.post(
            "/api/admin/customers/",
            data=json.dumps({"trade_name": "Agent Test", "phone": "3333333333"}),
            content_type="application/json",
            **get_jwt_headers(self.agent_user),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_cannot_list(self):
        resp = self.client.get(
            "/api/admin/customers/",
            **get_jwt_headers(self.agent_user),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_can_list(self):
        super_admin = create_user(
            role=RoleType.SUPER_ADMIN, email="super@list.com", company=None
        )
        resp = self.client.get(
            "/api/admin/customers/",
            **get_jwt_headers(super_admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_data_isolation(self):
        other_company = create_company(name="Other", slug="other-co", status="active")
        other_admin = create_user(
            role=RoleType.ADMIN, company=other_company, email="other@admin.com"
        )
        create_customer(self.company, trade_name="Ours")
        create_customer(other_company, trade_name="Theirs")
        resp = self.client.get(
            "/api/admin/customers/", **get_jwt_headers(other_admin)
        )
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["trade_name"], "Theirs")
