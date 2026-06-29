from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import RoleType, User
from apps.accounts.tests.factories import (
    create_agent_profile,
    create_company,
    create_invitation,
    create_membership,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import AgentCompanyMembership, AgentInvitation, AgentProfile
from apps.agents.views import AgentMembershipViewSet
from apps.orders.models import Order


class AgentManagementBase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.company = create_company(status="active")
        self.admin = create_user(
            role=RoleType.ADMIN, company=self.company, email="admin@mgmt.com"
        )
        self.admin_headers = get_jwt_headers(self.admin)

        self.agent_user = create_user(
            role=RoleType.AGENT,
            company=None,
            email="agent@mgmt.com",
        )
        self.agent_profile = create_agent_profile(self.agent_user)
        self.agent_headers = get_jwt_headers(self.agent_user)


class AdminAgentListTests(AgentManagementBase):
    def test_admin_list_agents_empty(self):
        view = AgentMembershipViewSet.as_view({"get": "list"})
        response = view(self.factory.get("/api/admin/agents", **self.admin_headers))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_admin_list_agents_with_memberships(self):
        membership = create_membership(
            self.agent_profile, self.company, status="active"
        )
        view = AgentMembershipViewSet.as_view({"get": "list"})
        response = view(self.factory.get("/api/admin/agents", **self.admin_headers))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], "active")
        self.assertEqual(
            response.data[0]["user"]["email"], "agent@mgmt.com"
        )

    def test_admin_list_agents_other_company_blocked(self):
        other_company = create_company(
            name="Other Co", slug="other-co", contact_email="other@co.com"
        )
        other_admin = create_user(
            role=RoleType.ADMIN,
            company=other_company,
            email="other-admin@mgmt.com",
        )
        other_headers = get_jwt_headers(other_admin)
        create_membership(self.agent_profile, self.company, status="active")

        view = AgentMembershipViewSet.as_view({"get": "list"})
        response = view(
            self.factory.get("/api/admin/agents", **other_headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_unauthenticated_cannot_list_agents(self):
        view = AgentMembershipViewSet.as_view({"get": "list"})
        response = self.factory.get("/api/admin/agents")
        response = view(response)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AdminAgentRetrieveTests(AgentManagementBase):
    def test_admin_retrieve_agent(self):
        membership = create_membership(
            self.agent_profile, self.company, status="active"
        )
        view = AgentMembershipViewSet.as_view({"get": "retrieve"})
        response = view(
            self.factory.get(f"/api/admin/agents/{membership.id}", **self.admin_headers),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(membership.id))

    def test_admin_retrieve_nonexistent_agent(self):
        view = AgentMembershipViewSet.as_view({"get": "retrieve"})
        response = view(
            self.factory.get(
                "/api/admin/agents/00000000-0000-0000-0000-000000000000",
                **self.admin_headers,
            ),
            pk="00000000-0000-0000-0000-000000000000",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminAgentUpdateTests(AgentManagementBase):
    def test_admin_update_agent_territory(self):
        membership = create_membership(
            self.agent_profile, self.company, status="active"
        )
        view = AgentMembershipViewSet.as_view({"patch": "partial_update"})
        response = view(
            self.factory.patch(
                f"/api/admin/agents/{membership.id}",
                {"territory": "North Zone"},
                format="json",
                **self.admin_headers,
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        membership.refresh_from_db()
        self.assertEqual(membership.territory, "North Zone")

    def test_admin_cannot_update_other_company_agent(self):
        other_company = create_company(
            name="Other Co", slug="other-co-2", contact_email="other2@co.com"
        )
        other_admin = create_user(
            role=RoleType.ADMIN,
            company=other_company,
            email="other-admin2@mgmt.com",
        )
        other_headers = get_jwt_headers(other_admin)
        membership = create_membership(
            self.agent_profile, self.company, status="active"
        )
        view = AgentMembershipViewSet.as_view({"patch": "partial_update"})
        response = view(
            self.factory.patch(
                f"/api/admin/agents/{membership.id}",
                {"territory": "East Zone"},
                format="json",
                **other_headers,
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminAgentDeleteTests(AgentManagementBase):
    def test_admin_remove_agent(self):
        membership = create_membership(
            self.agent_profile, self.company, status="active"
        )
        view = AgentMembershipViewSet.as_view({"delete": "destroy"})
        response = view(
            self.factory.delete(
                f"/api/admin/agents/{membership.id}", **self.admin_headers
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        membership.refresh_from_db()
        self.assertEqual(membership.status, "removed")
        self.assertIsNotNone(membership.removed_at)

        self.agent_user.refresh_from_db()
        self.assertFalse(self.agent_user.is_active)


class AgentApprovalFlowTests(AgentManagementBase):
    def setUp(self):
        super().setUp()
        self.membership = create_membership(
            self.agent_profile, self.company, status="pending"
        )

    def test_approve_pending_agent(self):
        view = AgentMembershipViewSet.as_view({"post": "approve"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/approve",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "active")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")
        self.assertEqual(self.membership.approved_by, self.admin)
        self.assertIsNotNone(self.membership.joined_at)

    def test_approve_already_active_rejected(self):
        self.membership.status = "active"
        self.membership.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "approve"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/approve",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_pending_agent(self):
        view = AgentMembershipViewSet.as_view({"post": "reject"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/reject",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "removed")
        self.assertIsNotNone(self.membership.removed_at)

    def test_reject_non_pending_rejected(self):
        self.membership.status = "active"
        self.membership.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "reject"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/reject",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_other_company_blocked(self):
        other_company = create_company(
            name="Other Co 3",
            slug="other-co-3",
            contact_email="other3@co.com",
        )
        other_admin = create_user(
            role=RoleType.ADMIN,
            company=other_company,
            email="other-admin3@mgmt.com",
        )
        other_headers = get_jwt_headers(other_admin)

        view = AgentMembershipViewSet.as_view({"post": "approve"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/approve",
                **other_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AgentSuspendReactivateTests(AgentManagementBase):
    def setUp(self):
        super().setUp()
        self.membership = create_membership(
            self.agent_profile, self.company, status="active"
        )

    def test_suspend_active_agent(self):
        view = AgentMembershipViewSet.as_view({"post": "suspend"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/suspend",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "suspended")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "suspended")

    def test_suspend_non_active_rejected(self):
        self.membership.status = "pending"
        self.membership.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "suspend"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/suspend",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reactivate_suspended_agent(self):
        self.membership.status = "suspended"
        self.membership.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "reactivate"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/reactivate",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "active")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "active")

    def test_reactivate_non_suspended_rejected(self):
        view = AgentMembershipViewSet.as_view({"post": "reactivate"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/reactivate",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AgentReviewFlowTests(AgentManagementBase):
    def setUp(self):
        super().setUp()
        self.sub_admin = create_user(
            role=RoleType.SUB_ADMIN,
            company=self.company,
            email="subadmin@mgmt.com",
        )
        self.sub_admin_headers = get_jwt_headers(self.sub_admin)
        self.membership = create_membership(
            self.agent_profile, self.company, status="pending"
        )

    def test_sub_admin_review_pending_agent(self):
        view = AgentMembershipViewSet.as_view({"post": "review"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/review",
                **self.sub_admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "reviewed")

        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "reviewed")
        self.assertEqual(self.membership.reviewed_by, self.sub_admin)
        self.assertIsNotNone(self.membership.reviewed_at)

    def test_review_to_approve_two_step(self):
        view = AgentMembershipViewSet.as_view({"post": "review"})
        view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/review",
                **self.sub_admin_headers,
            ),
            pk=self.membership.id,
        )
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.status, "reviewed")

        view = AgentMembershipViewSet.as_view({"post": "approve"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/approve",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "active")

    def test_review_non_pending_rejected(self):
        self.membership.status = "active"
        self.membership.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "review"})
        response = view(
            self.factory.post(
                f"/api/admin/agents/{self.membership.id}/review",
                **self.sub_admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AgentPerformanceTests(AgentManagementBase):
    def setUp(self):
        super().setUp()
        self.membership = create_membership(
            self.agent_profile, self.company, status="active",
        )
        self.membership.monthly_target = 100000
        self.membership.save(update_fields=["monthly_target"])

    def test_agent_my_performance_requires_company_context(self):
        view = AgentMembershipViewSet.as_view({"get": "my_performance"})
        response = view(
            self.factory.get(
                "/api/auth/agents/performance", **self.agent_headers
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active company", response.data["detail"])

    def test_agent_my_performance_with_x_company_id(self):
        view = AgentMembershipViewSet.as_view({"get": "my_performance"})
        response = view(
            self.factory.get(
                "/api/auth/agents/performance",
                HTTP_X_COMPANY_ID=str(self.company.id),
                **self.agent_headers,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("orders_this_month", response.data)
        self.assertIn("sales_this_month", response.data)
        self.assertIn("monthly_target", response.data)

    def test_admin_view_agent_performance(self):
        view = AgentMembershipViewSet.as_view({"get": "agent_performance"})
        response = view(
            self.factory.get(
                f"/api/admin/agents/{self.membership.id}/performance",
                **self.admin_headers,
            ),
            pk=self.membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("orders_this_month", response.data)
        self.assertIn("sales_this_month", response.data)
        self.assertIn("commission_earned", response.data)
        self.assertIn("commission_preview", response.data)

    def test_leaderboard_empty(self):
        view = AgentMembershipViewSet.as_view({"get": "leaderboard"})
        response = view(
            self.factory.get(
                "/api/admin/agents/leaderboard", **self.admin_headers
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_leaderboard_with_orders(self):
        from apps.accounts.tests.factories import get_jwt_headers as gjh
        from apps.customers.models import CustomerProfile

        customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Test Customer",
            owner_name="Owner",
            phone="9999999999",
        )
        Order.objects.create(
            company=self.company,
            agent=self.agent_profile,
            customer=customer,
            order_number="ORD-001",
            total_amount=50000,
            status="submitted",
            submitted_at="2026-06-01",
        )

        view = AgentMembershipViewSet.as_view({"get": "leaderboard"})
        response = view(
            self.factory.get(
                "/api/admin/agents/leaderboard", **self.admin_headers
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["full_name"], "Agent User")
        self.assertEqual(response.data[0]["sales_this_month"], "50000.00")


class AgentMultiCompanyTests(AgentManagementBase):
    def setUp(self):
        super().setUp()
        self.membership = create_membership(
            self.agent_profile, self.company, status="active",
        )
        self.company2 = create_company(
            name="Company Two",
            slug="company-two",
            contact_email="two@co.com",
        )
        self.membership2 = create_membership(
            self.agent_profile, self.company2, status="active",
        )

    def test_agent_list_companies(self):
        view = AgentMembershipViewSet.as_view({"get": "my_companies"})
        response = view(
            self.factory.get(
                "/api/auth/agents/companies", **self.agent_headers
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        company_names = {c["name"] for c in response.data}
        self.assertIn("Test Company", company_names)
        self.assertIn("Company Two", company_names)

    def test_agent_switch_company(self):
        view = AgentMembershipViewSet.as_view({"post": "switch_company"})
        response = view(
            self.factory.post(
                "/api/auth/agents/switch-company",
                {"company_id": str(self.company2.id)},
                format="json",
                **self.agent_headers,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["company_id"], str(self.company2.id))

    def test_agent_switch_to_unrelated_company_blocked(self):
        company3 = create_company(
            name="Company Three",
            slug="company-three",
            contact_email="three@co.com",
        )
        view = AgentMembershipViewSet.as_view({"post": "switch_company"})
        response = view(
            self.factory.post(
                "/api/auth/agents/switch-company",
                {"company_id": str(company3.id)},
                format="json",
                **self.agent_headers,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_switch_company_inactive_membership_blocked(self):
        self.membership2.status = "suspended"
        self.membership2.save(update_fields=["status"])

        view = AgentMembershipViewSet.as_view({"post": "switch_company"})
        response = view(
            self.factory.post(
                "/api/auth/agents/switch-company",
                {"company_id": str(self.company2.id)},
                format="json",
                **self.agent_headers,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_switch_company_missing_id(self):
        view = AgentMembershipViewSet.as_view({"post": "switch_company"})
        response = view(
            self.factory.post(
                "/api/auth/agents/switch-company",
                {},
                format="json",
                **self.agent_headers,
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_agent_cannot_list_companies(self):
        view = AgentMembershipViewSet.as_view({"get": "my_companies"})
        response = view(
            self.factory.get(
                "/api/auth/agents/companies", **self.admin_headers
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AgentFullLifecycleTest(TestCase):
    def test_full_agent_lifecycle(self):
        factory = APIRequestFactory()

        # 1. Register agent
        from apps.accounts.views import AgentRegisterView

        register_view = AgentRegisterView.as_view({"post": "create"})
        reg_data = {
            "email": "lifecycle@test.com",
            "password": "Test@12345678",
            "full_name": "Lifecycle Agent",
            "phone": "8888888888",
        }
        response = register_view(
            factory.post("/api/auth/agents/register", reg_data, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        agent_user = User.objects.get(email="lifecycle@test.com")
        agent_profile = AgentProfile.objects.get(user=agent_user)
        agent_headers = get_jwt_headers(agent_user)

        # 2. Create company with admin
        company = create_company(status="active")
        admin = create_user(
            role=RoleType.ADMIN, company=company, email="lifecycle-admin@test.com"
        )
        admin_headers = get_jwt_headers(admin)

        # 3. Create invitation
        invitation = create_invitation(company=company, invited_by=admin)

        # 4. Agent joins (now pending)
        from apps.accounts.views import AuthViewSet

        join_view = AuthViewSet.as_view({"post": "join_company"})
        response = join_view(
            factory.post(
                "/api/auth/agents/join",
                {"invite_code": invitation.token},
                format="json",
                **agent_headers,
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["membership_status"], "pending")

        membership = AgentCompanyMembership.objects.get(
            agent=agent_profile, company=company
        )
        self.assertEqual(membership.status, "pending")

        # 5. Admin approves
        from apps.agents.views import AgentMembershipViewSet

        approve_view = AgentMembershipViewSet.as_view({"post": "approve"})
        response = approve_view(
            factory.post(
                f"/api/admin/agents/{membership.id}/approve",
                **admin_headers,
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "active")

        membership.refresh_from_db()
        self.assertEqual(membership.status, "active")

        # 6. Admin suspends
        suspend_view = AgentMembershipViewSet.as_view({"post": "suspend"})
        response = suspend_view(
            factory.post(
                f"/api/admin/agents/{membership.id}/suspend",
                **admin_headers,
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "suspended")

        # 7. Admin reactivates
        reactivate_view = AgentMembershipViewSet.as_view({"post": "reactivate"})
        response = reactivate_view(
            factory.post(
                f"/api/admin/agents/{membership.id}/reactivate",
                **admin_headers,
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "active")

        # 8. Admin removes agent
        destroy_view = AgentMembershipViewSet.as_view({"delete": "destroy"})
        response = destroy_view(
            factory.delete(
                f"/api/admin/agents/{membership.id}", **admin_headers
            ),
            pk=membership.id,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
