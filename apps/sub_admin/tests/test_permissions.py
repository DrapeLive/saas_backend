from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import (
    Permission,
    RoleTemplate,
    RoleTemplatePermission,
    RoleType,
    SubAdminPermission,
    SubAdminProfile,
    User,
)
from apps.companies.models import Company, CompanySettings
from apps.products.models import Category


class PermissionFixtureMixin:
    def setUp(self):
        self.company = Company.objects.create(
            name="Acme Apparel",
            slug="acme-permissions",
            contact_email="acme@example.com",
            contact_phone="9999999999",
            state="Maharashtra",
        )
        CompanySettings.objects.create(
            company=self.company,
            order_approval_required=False,
            order_auto_confirm=False,
            credit_block_on_exceed=False,
        )
        self.admin = User.objects.create_user(
            email="admin@acme.test",
            password="Str0ngPass!23",
            full_name="Admin One",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.template = RoleTemplate.objects.create(
            company=self.company, name="Catalog view only", rank=40
        )
        RoleTemplatePermission.objects.create(
            role_template=self.template,
            module="products",
            can_view=True,
        )
        self.subadmin = User.objects.create_user(
            email="sub@acme.test",
            password="Str0ngPass!23",
            full_name="Sub One",
            role=RoleType.SUB_ADMIN,
            company=self.company,
        )
        self.profile = SubAdminProfile.objects.create(
            user=self.subadmin, role_template=self.template
        )
        self.category = Category.objects.create(
            company=self.company, name="Mens", hsn_code="6109"
        )
        self.sub_client = APIClient()
        self.sub_client.force_authenticate(user=self.subadmin)
        self.sub_jwt_client = APIClient()
        token = AccessToken.for_user(self.subadmin)
        self.sub_jwt_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def allow(self, module, **flags):
        RoleTemplatePermission.objects.update_or_create(
            role_template=self.template,
            module=module,
            defaults=flags,
        )


class ModulePermissionTests(PermissionFixtureMixin, TestCase):
    def test_view_permission_allows_list(self):
        response = self.sub_client.get("/api/categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_view_permission_denies_create(self):
        response = self.sub_client.post(
            "/api/categories/", {"name": "New"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("create products", response.data["detail"])

    def test_add_permission_allows_create(self):
        self.allow("products", can_view=True, can_add=True)
        response = self.sub_client.post(
            "/api/categories/", {"name": "New"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_edit_permission_denies_then_allows(self):
        url = f"/api/categories/{self.category.id}/"
        response = self.sub_client.patch(url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.allow("products", can_view=True, can_edit=True)
        response = self.sub_client.patch(url, {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_delete_permission_denied(self):
        response = self.sub_client.delete(f"/api/categories/{self.category.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_module_without_rule_is_denied(self):
        self.sub_client.force_authenticate(user=self.subadmin)
        response = self.sub_client.get("/api/reports/sales/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subadmin_override_wins_over_template(self):
        RoleTemplatePermission.objects.filter(
            role_template=self.template, module="products"
        ).update(can_view=False)
        SubAdminPermission.objects.create(
            sub_admin=self.profile, module="products", can_view=True
        )
        response = self.sub_client.get("/api/categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_profile_without_rules_is_denied(self):
        empty_template = RoleTemplate.objects.create(
            company=self.company, name="Empty", rank=10
        )
        self.profile.role_template = empty_template
        self.profile.save(update_fields=["role_template"])
        response = self.sub_client.get("/api/categories/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AuthPayloadTests(PermissionFixtureMixin, TestCase):
    def test_me_returns_permissions_and_restrictions(self):
        self.sub_client.force_authenticate(user=self.subadmin)
        response = self.sub_client.get("/api/auth/me")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(modules["products"]["can_view"])
        self.assertFalse(modules["products"]["can_add"])
        self.assertFalse(modules["orders"]["can_view"])
        self.assertIn("restrictions", response.data)

    def test_login_returns_permissions_for_subadmin(self):
        response = APIClient().post(
            "/api/auth/login",
            {"email": "sub@acme.test", "password": "Str0ngPass!23"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(modules["products"]["can_view"])
        self.assertFalse(modules["orders"]["can_view"])

    def test_admin_payload_has_full_permissions(self):
        response = self.admin_client.get("/api/auth/me")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(all(row["can_view"] for row in modules.values()))


class EscalationTests(PermissionFixtureMixin, TestCase):
    def test_subadmin_cannot_list_permissions_catalog(self):
        response = self.sub_client.get("/api/admin/permissions")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subadmin_cannot_create_role_template(self):
        response = self.sub_client.post(
            "/api/admin/role-templates",
            {"name": "Escalate", "permissions": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subadmin_cannot_edit_own_permissions(self):
        response = self.sub_client.patch(
            f"/api/admin/sub-admins/{self.subadmin.id}",
            {"permissions": [{"module": "orders", "can_view": True}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # The self-service profile endpoint only updates safe fields.
        response = self.sub_client.patch(
            "/api/auth/me",
            {"permissions": [{"module": "orders", "can_view": True}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            SubAdminPermission.objects.filter(
                sub_admin=self.profile, module="orders"
            ).exists()
        )

    def test_subadmin_cannot_manage_other_users(self):
        response = self.sub_client.patch(
            f"/api/admin/users/{self.admin.id}",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminSubAdminManagementTests(PermissionFixtureMixin, TestCase):
    def _create_payload(self, **overrides):
        payload = {
            "email": "new-sub@acme.test",
            "password": "Str0ngPass!23",
            "full_name": "New Sub",
            "role_template_id": None,
            "permissions": [
                {
                    "module": "orders",
                    "can_view": True,
                    "can_add": True,
                    "can_edit": False,
                    "can_delete": False,
                    "can_export": False,
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_create_subadmin_persists_permissions(self):
        response = self.admin_client.post(
            "/api/admin/sub-admins", self._create_payload(), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(modules["orders"]["can_view"])
        self.assertTrue(modules["orders"]["can_add"])
        self.assertFalse(modules["products"]["can_view"])

    def test_update_subadmin_permissions(self):
        response = self.admin_client.patch(
            f"/api/admin/sub-admins/{self.subadmin.id}",
            {
                "permissions": [
                    {"module": "orders", "can_view": True, "can_edit": True},
                    {"module": "products", "can_view": False},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(modules["orders"]["can_view"])
        self.assertTrue(modules["orders"]["can_edit"])
        self.assertFalse(modules["products"]["can_view"])

    def test_cross_company_template_rejected(self):
        other_company = Company.objects.create(
            name="Other Co",
            slug="other-co",
            contact_email="other@example.com",
            contact_phone="8888888888",
            state="Maharashtra",
        )
        other_template = RoleTemplate.objects.create(
            company=other_company, name="Other", rank=10
        )
        response = self.admin_client.post(
            "/api/admin/sub-admins",
            self._create_payload(role_template_id=str(other_template.id)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivated_subadmin_is_rejected(self):
        response = self.admin_client.patch(
            f"/api/admin/sub-admins/{self.subadmin.id}",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data["is_active"])

        response = self.sub_jwt_client.get("/api/auth/me")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_role_template_create_accepts_module_matrix(self):
        response = self.admin_client.post(
            "/api/admin/role-templates",
            {
                "name": "Ops",
                "permissions": [
                    {
                        "module": "orders",
                        "can_view": True,
                        "can_add": True,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        modules = {row["module"]: row for row in response.data["permissions"]}
        self.assertTrue(modules["orders"]["can_add"])
        self.assertEqual(modules["orders"]["can_view"], True)
