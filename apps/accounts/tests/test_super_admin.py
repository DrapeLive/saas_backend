from datetime import timedelta

from django.test import TestCase
from django.utils.timezone import now
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
from apps.subscriptions.models import BillingCycle, Plan, Subscription, SubscriptionStatus


class SuperAdminCompanyTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.list_view = SuperAdminCompanyViewSet.as_view({"get": "list"})
        self.retrieve_view = SuperAdminCompanyViewSet.as_view({"get": "retrieve"})
        self.status_view = SuperAdminCompanyViewSet.as_view({"post": "update_status"})

        self.plan = Plan.objects.create(
            tier="starter", name="Starter",
            monthly_price=1999, yearly_price=19990,
        )
        self.sub = Subscription.objects.create(
            plan=self.plan, status=SubscriptionStatus.TRIAL,
            billing_cycle=BillingCycle.TRIAL,
            trial_end=now().date() + timedelta(days=14),
        )
        self.company = create_company(
            status=CompanyStatus.PENDING, subscription=self.sub,
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

    # --- Management action tests ---

    def setUp_action_views(self):
        self.suspend_view = SuperAdminCompanyViewSet.as_view({"post": "suspend"})
        self.activate_view = SuperAdminCompanyViewSet.as_view({"post": "activate"})
        self.extend_trial_view = SuperAdminCompanyViewSet.as_view({"post": "extend_trial"})
        self.impersonate_view = SuperAdminCompanyViewSet.as_view({"post": "impersonate"})
        self.delete_view = SuperAdminCompanyViewSet.as_view({"delete": "destroy"})

    def test_suspend_success(self):
        self.setUp_action_views()
        co = create_company(name="Suspend Co", slug="suspend-co", contact_email="sus@co.com")
        response = self.suspend_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/suspend", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        co.refresh_from_db()
        self.assertEqual(co.status, "suspended")

    def test_suspend_already_suspended(self):
        self.setUp_action_views()
        co = create_company(name="Already Susp Co", slug="already-susp", contact_email="as@co.com", status=CompanyStatus.SUSPENDED)
        response = self.suspend_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/suspend", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suspend_nonexistent(self):
        self.setUp_action_views()
        from uuid import uuid4
        response = self.suspend_view(
            self.factory.post(f"/api/super-admin/companies/{uuid4()}/suspend", **self.super_headers),
            pk=uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_activate_success(self):
        self.setUp_action_views()
        co = create_company(name="Activate Co", slug="activate-co", contact_email="act@co.com", status=CompanyStatus.SUSPENDED)
        response = self.activate_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/activate", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        co.refresh_from_db()
        self.assertEqual(co.status, "active")

    def test_activate_not_suspended(self):
        self.setUp_action_views()
        co = create_company(name="Active Co", slug="active-co", contact_email="actv@co.com", status=CompanyStatus.TRIAL)
        response = self.activate_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/activate", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_extend_trial_success(self):
        self.setUp_action_views()
        sub = Subscription.objects.create(plan=self.plan, status=SubscriptionStatus.TRIAL, billing_cycle=BillingCycle.TRIAL, trial_end=now().date() + timedelta(days=14))
        co = create_company(name="Extend Co", slug="extend-co", contact_email="ext@co.com", subscription=sub)
        old_end = sub.trial_end
        response = self.extend_trial_view(
            self.factory.post(
                f"/api/super-admin/companies/{co.pk}/extend-trial",
                {"days": 7, "reason": "Customer requested"},
                format="json",
                **self.super_headers,
            ),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sub.refresh_from_db()
        self.assertEqual(sub.trial_end, old_end + timedelta(days=7))

    def test_extend_trial_no_subscription(self):
        self.setUp_action_views()
        co = create_company(name="No Sub Co", slug="no-sub-co", contact_email="nosub@co.com")
        response = self.extend_trial_view(
            self.factory.post(
                f"/api/super-admin/companies/{co.pk}/extend-trial",
                {"days": 7, "reason": "test"},
                format="json",
                **self.super_headers,
            ),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_extend_trial_not_trial_status(self):
        self.setUp_action_views()
        sub = Subscription.objects.create(plan=self.plan, status=SubscriptionStatus.ACTIVE, billing_cycle=BillingCycle.MONTHLY)
        co = create_company(name="Not Trial Co", slug="not-trial-co", contact_email="nt@co.com", subscription=sub)
        response = self.extend_trial_view(
            self.factory.post(
                f"/api/super-admin/companies/{co.pk}/extend-trial",
                {"days": 7, "reason": "test"},
                format="json",
                **self.super_headers,
            ),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_impersonate_success(self):
        self.setUp_action_views()
        co = create_company(name="Impersonate Co", slug="imp-co", contact_email="imp@co.com")
        admin_user = create_user(role=RoleType.ADMIN, company=co, email="imp-admin@co.com")
        response = self.impersonate_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/impersonate", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["expires_in"], 1800)

    def test_impersonate_no_admin(self):
        self.setUp_action_views()
        co = create_company(name="No Admin Co", slug="no-admin-co", contact_email="nadm@co.com")
        response = self.impersonate_view(
            self.factory.post(f"/api/super-admin/companies/{co.pk}/impersonate", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_destroy_success(self):
        self.setUp_action_views()
        co = create_company(name="Delete Co", slug="delete-co", contact_email="del@co.com", status=CompanyStatus.TRIAL)
        response = self.delete_view(
            self.factory.delete(f"/api/super-admin/companies/{co.pk}", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        co.refresh_from_db()
        self.assertTrue(co.is_deleted)
        self.assertIsNotNone(co.deleted_at)
        self.assertEqual(co.status, "expired")

    def test_destroy_active_company(self):
        self.setUp_action_views()
        co = create_company(name="Active Del Co", slug="active-del-co", contact_email="adel@co.com", status=CompanyStatus.ACTIVE)
        response = self.delete_view(
            self.factory.delete(f"/api/super-admin/companies/{co.pk}", **self.super_headers),
            pk=co.pk,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_destroy_nonexistent(self):
        self.setUp_action_views()
        from uuid import uuid4
        response = self.delete_view(
            self.factory.delete(f"/api/super-admin/companies/{uuid4()}", **self.super_headers),
            pk=uuid4(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
