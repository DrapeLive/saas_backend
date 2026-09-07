"""Tests for the agent profile API (`/api/auth/agents/profile`)."""

from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import (
    AgentCompanyMembership,
    AgentProfile,
)


def create_agent(company, email, full_name, company_2=None):
    user = create_user(
        role=RoleType.AGENT,
        company=None,
        email=email,
        full_name=full_name,
    )
    profile = AgentProfile.objects.create(
        user=user,
        total_sales=Decimal("1250.75"),
        total_orders=12,
        leaderboard_rank=2,
    )
    AgentCompanyMembership.objects.create(
        agent=profile,
        company=company,
        status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        territory="North",
    )
    if company_2 is not None:
        AgentCompanyMembership.objects.create(
            agent=profile,
            company=company_2,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
            territory="South",
        )
    return profile


class AgentProfileApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.other_company = create_company(name="Other Co", status="active")
        self.agent = create_agent(
            self.company, "agent@profile.com", "Profile Agent", self.other_company
        )
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_profile_returns_expected_fields(self):
        resp = self.client.get("/api/auth/agents/profile")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["full_name"], "Profile Agent")
        self.assertEqual(resp.data["total_sales"], "1250.75")
        self.assertEqual(resp.data["total_orders"], 12)
        self.assertEqual(resp.data["leaderboard_rank"], 2)

    def test_profile_lists_all_joined_companies(self):
        resp = self.client.get("/api/auth/agents/profile")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        companies = resp.data["joined_companies"]
        self.assertEqual(len(companies), 2)
        names = {c["name"] for c in companies}
        self.assertEqual(names, {self.company.name, self.other_company.name})

        active = next(
            c for c in companies if c["name"] == self.company.name
        )
        self.assertEqual(active["membership_status"], "active")
        self.assertEqual(active["territory"], "North")

    def test_profile_returns_404_without_agent_profile(self):
        user = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="admin@profile.com",
        )
        self.client.credentials(**get_jwt_headers(user))
        resp = self.client.get("/api/auth/agents/profile")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("detail", resp.data)

    def test_profile_requires_authentication(self):
        self.client.credentials()
        resp = self.client.get("/api/auth/agents/profile")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)