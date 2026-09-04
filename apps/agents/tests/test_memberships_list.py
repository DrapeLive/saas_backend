from django.test import TestCase
from apps.accounts.models import RoleType
from apps.accounts.tests.factories import create_company, create_user, get_jwt_headers
from apps.agents.models import AgentCompanyMembership, AgentProfile


class MembershipsListTest(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.subadmin = create_user(role=RoleType.SUB_ADMIN, company=self.company)

        agent_user = create_user(
            role=RoleType.AGENT, company=self.company, email="agent@x.com"
        )
        self.profile = AgentProfile.objects.create(
            user=agent_user, employee_code="AG-1"
        )
        AgentCompanyMembership.objects.create(
            agent=self.profile,
            company=self.company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
            territory="North",
        )

    def _hit(self, user):
        return self.client.get(
            "/api/admin/agents/agent-memberships",
            **get_jwt_headers(user),
        )

    def test_admin_allowed_and_sees_membership(self):
        r = self._hit(self.admin)
        print("ADMIN  ->", r.status_code)
        self.assertEqual(r.status_code, 200)

    def test_subadmin_allowed(self):
        r = self._hit(self.subadmin)
        print("SUBADMIN ->", r.status_code)
        self.assertEqual(r.status_code, 200)

    def test_agent_denied(self):
        agent_user = create_user(
            role=RoleType.AGENT, company=self.company, email="agent2@x.com"
        )
        r = self._hit(agent_user)
        print("AGENT  ->", r.status_code)
        self.assertEqual(r.status_code, 403)
