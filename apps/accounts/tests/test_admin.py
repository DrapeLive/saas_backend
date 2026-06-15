from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleType, User
from apps.accounts.views import AdminUserViewSet, InvitationViewSet
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    create_super_admin,
    get_jwt_headers,
)
from apps.agents.models import AgentInvitation


class UserManagementTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.list_view = AdminUserViewSet.as_view({"get": "list"})
        self.create_view = AdminUserViewSet.as_view({"post": "create_sub_admin"})
        self.update_view = AdminUserViewSet.as_view({"patch": "update"})
        self.delete_view = AdminUserViewSet.as_view({"delete": "destroy"})

        self.company = create_company()
        self.admin = create_user(
            role=RoleType.ADMIN, company=self.company, email="admin@company.com"
        )
        self.sub_admin = create_user(
            role=RoleType.SUB_ADMIN,
            company=self.company,
            email="subadmin@company.com",
            full_name="Sub Admin",
        )
        self.admin_headers = get_jwt_headers(self.admin)
        self.super_admin = create_super_admin()
        self.super_headers = get_jwt_headers(self.super_admin)

    def test_admin_list_users_scoped_to_own_company(self):
        other_company = create_company(
            name="Other Co", slug="other-co", contact_email="other@co.com"
        )
        create_user(role=RoleType.ADMIN, company=other_company, email="other@admin.com")
        response = self.list_view(
            self.factory.get("/api/admin/users", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {u["email"] for u in response.data}
        self.assertIn("admin@company.com", emails)
        self.assertIn("subadmin@company.com", emails)
        self.assertNotIn("other@admin.com", emails)

    def test_super_admin_list_all_users(self):
        other_company = create_company(
            name="Other Co", slug="other-co-2", contact_email="other2@co.com"
        )
        create_user(role=RoleType.ADMIN, company=other_company, email="other@admin.com")
        response = self.list_view(
            self.factory.get("/api/admin/users", **self.super_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {u["email"] for u in response.data}
        self.assertIn("admin@company.com", emails)
        self.assertIn("other@admin.com", emails)

    def test_create_sub_admin(self):
        response = self.create_view(
            self.factory.post("/api/admin/users", {
                "email": "newsub@company.com",
                "password": "SubPass@123",
                "full_name": "New Sub",
            }, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="newsub@company.com")
        self.assertEqual(user.role, RoleType.SUB_ADMIN)
        self.assertEqual(user.company, self.company)

    def test_create_sub_admin_missing_fields(self):
        response = self.create_view(
            self.factory.post("/api/admin/users", {}, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_user(self):
        response = self.update_view(
            self.factory.patch(
                f"/api/admin/users/{self.sub_admin.pk}",
                {"full_name": "Updated Name"},
                format="json",
                **self.admin_headers,
            ),
            pk=self.sub_admin.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.sub_admin.refresh_from_db()
        self.assertEqual(self.sub_admin.full_name, "Updated Name")

    def test_update_user_not_found(self):
        from uuid import uuid4
        response = self.update_view(
            self.factory.patch(
                f"/api/admin/users/{uuid4()}",
                {"full_name": "Nope"},
                format="json",
                **self.admin_headers,
            ),
            pk=uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deactivate_user(self):
        response = self.delete_view(
            self.factory.delete(
                f"/api/admin/users/{self.sub_admin.pk}",
                **self.admin_headers,
            ),
            pk=self.sub_admin.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.sub_admin.refresh_from_db()
        self.assertFalse(self.sub_admin.is_active)

    def test_cannot_manage_other_company_user_as_admin(self):
        other_company = create_company(
            name="Other", slug="other-slug", contact_email="o@o.com"
        )
        other_user = create_user(
            role=RoleType.SUB_ADMIN, company=other_company, email="other@user.com"
        )
        response = self.update_view(
            self.factory.patch(
                f"/api/admin/users/{other_user.pk}",
                {"full_name": "Hacked"},
                format="json",
                **self.admin_headers,
            ),
            pk=other_user.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_update_any_user(self):
        other_company = create_company(
            name="Other2", slug="other2-slug", contact_email="o2@o.com"
        )
        other_user = create_user(
            role=RoleType.SUB_ADMIN, company=other_company, email="other2@user.com"
        )
        response = self.update_view(
            self.factory.patch(
                f"/api/admin/users/{other_user.pk}",
                {"full_name": "Super Updated"},
                format="json",
                **self.super_headers,
            ),
            pk=other_user.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        other_user.refresh_from_db()
        self.assertEqual(other_user.full_name, "Super Updated")

    def test_admin_cannot_create_sub_admin_for_another_company(self):
        response = self.create_view(
            self.factory.post("/api/admin/users", {
                "email": "hacker@evil.com",
                "password": "Hack@123456",
                "full_name": "Hacker",
                "company": "some-company-id",
            }, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="hacker@evil.com")
        self.assertEqual(user.company, self.company)


class InvitationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.list_view = InvitationViewSet.as_view({"get": "list"})
        self.create_view = InvitationViewSet.as_view({"post": "create"})
        self.company = create_company()
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.admin_headers = get_jwt_headers(self.admin)

    def test_create_invitation(self):
        response = self.create_view(
            self.factory.post("/api/admin/invitations", {
                "email": "agent@invite.com",
                "delivery_method": "email",
            }, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", response.data)
        self.assertEqual(response.data["email"], "agent@invite.com")
        self.assertEqual(response.data["status"], "pending")
        self.assertTrue(AgentInvitation.objects.filter(email="agent@invite.com").exists())

    def test_create_invitation_with_phone(self):
        response = self.create_view(
            self.factory.post("/api/admin/invitations", {
                "phone": "1234567890",
                "delivery_method": "whatsapp",
            }, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["phone"], "1234567890")

    def test_create_invitation_missing_contact(self):
        response = self.create_view(
            self.factory.post("/api/admin/invitations", {
                "delivery_method": "email",
            }, format="json", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_invitations(self):
        for i in range(3):
            AgentInvitation.objects.create(
                company=self.company,
                invited_by=self.admin,
                email=f"agent{i}@test.com",
                token=f"token{i}",
                delivery_method="email",
                expires_at="2027-01-01T00:00:00Z",
            )
        response = self.list_view(
            self.factory.get("/api/admin/invitations", **self.admin_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)

    def test_invitation_scoped_to_company(self):
        other_co = create_company(
            name="Other", slug="other-inv", contact_email="other@inv.com"
        )
        AgentInvitation.objects.create(
            company=other_co,
            invited_by=self.admin,
            email="other@agent.com",
            token="other-token",
            delivery_method="email",
            expires_at="2027-01-01T00:00:00Z",
        )
        response = self.list_view(
            self.factory.get("/api/admin/invitations", **self.admin_headers)
        )
        self.assertEqual(len(response.data), 0)

    def test_agent_cannot_create_invitation(self):
        agent_user = create_user(
            role=RoleType.AGENT, company=None, email="agent@test.com"
        )
        agent_headers = get_jwt_headers(agent_user)
        response = self.create_view(
            self.factory.post("/api/admin/invitations", {
                "email": "foo@test.com",
                "delivery_method": "email",
            }, format="json", **agent_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_create_invitation(self):
        response = self.create_view(
            self.factory.post("/api/admin/invitations", {
                "email": "foo@test.com",
                "delivery_method": "email",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
