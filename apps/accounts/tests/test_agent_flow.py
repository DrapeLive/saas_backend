from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleType, User
from apps.accounts.views import AgentRegisterView, AuthViewSet
from apps.accounts.tests.factories import (
    create_company,
    create_invitation,
    create_agent_profile,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import AgentCompanyMembership, AgentInvitation, AgentProfile


class AgentRegisterTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AgentRegisterView.as_view({"post": "create"})
        self.valid_data = {
            "email": "agent@test.com",
            "password": "AgentPass@123",
            "full_name": "Test Agent",
            "phone": "9876543210",
        }

    def test_agent_register_success(self):
        response = self.view(
            self.factory.post("/api/auth/agents/register", self.valid_data, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email="agent@test.com")
        self.assertEqual(user.role, RoleType.AGENT)
        self.assertIsNone(user.company)
        self.assertTrue(AgentProfile.objects.filter(user=user).exists())

    def test_agent_register_duplicate_email(self):
        self.view(
            self.factory.post("/api/auth/agents/register", self.valid_data, format="json")
        )
        response = self.view(
            self.factory.post("/api/auth/agents/register", self.valid_data, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_register_missing_fields(self):
        response = self.view(
            self.factory.post("/api/auth/agents/register", {}, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_register_weak_password(self):
        data = dict(self.valid_data)
        data["password"] = "123"
        response = self.view(
            self.factory.post("/api/auth/agents/register", data, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_register_no_company_assigned(self):
        response = self.view(
            self.factory.post("/api/auth/agents/register", self.valid_data, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data.get("company"))


class AgentJoinTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AuthViewSet.as_view({"post": "join_company"})
        self.company = create_company()
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.invitation = create_invitation(
            company=self.company,
            invited_by=self.admin,
        )
        self.agent_user = create_user(
            role=RoleType.AGENT, company=None, email="agent@join.com"
        )
        self.agent_profile = create_agent_profile(self.agent_user)
        self.agent_headers = get_jwt_headers(self.agent_user)

    def test_agent_join_with_valid_code(self):
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Successfully joined", response.data["detail"])
        self.assertEqual(response.data["membership_status"], "pending")

        membership = AgentCompanyMembership.objects.get(
            agent=self.agent_profile, company=self.company
        )
        self.assertEqual(membership.status, "pending")
        self.assertEqual(membership.invitation_method, "email")

        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.used_count, 1)

    def test_agent_join_invalid_code(self):
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": "invalid-token"},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_join_expired_code(self):
        from django.utils import timezone
        self.invitation.expires_at = timezone.now() - timezone.timedelta(hours=1)
        self.invitation.save(update_fields=["expires_at"])
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_join_non_agent_rejected(self):
        admin_headers = get_jwt_headers(self.admin)
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
                **admin_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_join_unauthenticated(self):
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
            )
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_agent_join_multiple_companies(self):
        company2 = create_company(
            name="Second Company", slug="second-company",
            contact_email="c2@test.com",
        )
        inv2 = create_invitation(company=company2, invited_by=self.admin)
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": inv2.token},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            AgentCompanyMembership.objects.filter(agent=self.agent_profile).count(), 2
        )

    def test_agent_accepts_only_once(self):
        self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
                **self.agent_headers,
            )
        )
        response = self.view(
            self.factory.post(
                "/api/auth/agents/join",
                {"invite_code": self.invitation.token},
                format="json",
                **self.agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
