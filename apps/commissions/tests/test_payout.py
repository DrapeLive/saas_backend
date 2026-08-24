from datetime import date
import uuid

from django.test import TestCase
from rest_framework import status

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.commissions.models import CommissionEntry, CommissionPayout
from apps.customers.models import CustomerProfile
from apps.orders.models import Order


class PayoutTestCase(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        user = create_user(
            role=RoleType.AGENT,
            company=self.company,
            email="payout-agent@x.com",
            full_name="Payout Agent",
        )
        self.agent = AgentProfile.objects.create(user=user, employee_code="AG-PAYOUT")
        AgentCompanyMembership.objects.create(
            agent=self.agent,
            company=self.company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
            territory="North",
        )
        customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Payout Cust",
            legal_name="Payout Cust Pvt Ltd",
            phone="9123456780",
        )
        month = date(2026, 8, 1)

        def make_order():
            return Order.objects.create(
                company=self.company,
                order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
                customer=customer,
                status="dispatched",
            )

        self.entry_a = CommissionEntry.objects.create(
            company=self.company,
            agent=self.agent,
            order=make_order(),
            order_value=1000,
            commission_pct=10.00,
            commission_amount=100.00,
            status=CommissionEntry.EntryStatus.APPROVED,
            settlement_month=month,
        )
        self.entry_b = CommissionEntry.objects.create(
            company=self.company,
            agent=self.agent,
            order=make_order(),
            order_value=2000,
            commission_pct=10.00,
            commission_amount=200.00,
            status=CommissionEntry.EntryStatus.APPROVED,
            settlement_month=month,
        )
        self.month = month


class SettleCreatesPayoutTests(PayoutTestCase):
    def test_settle_creates_payout_snapshot(self):
        resp = self.client.post(
            "/api/commission-entries/settle/",
            data='{"agent_id": "%s", "settlement_month": "2026-08-01"}' % self.agent.id,
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payout = CommissionPayout.objects.get(
            company=self.company, agent=self.agent, settlement_month=self.month
        )
        self.assertEqual(payout.amount, 300.00)
        self.assertEqual(payout.entries_count, 2)
        self.assertEqual(payout.paid_by_id, self.admin.id)
        self.assertIsNotNone(payout.paid_at)

    def test_resettle_recomputes_instead_of_duplicating(self):
        self.client.post(
            "/api/commission-entries/settle/",
            data='{"agent_id": "%s", "settlement_month": "2026-08-01"}' % self.agent.id,
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        # A late entry gets paid individually afterwards.
        self.entry_a.refresh_from_db()
        resp = self.client.post(
            f"/api/commission-entries/{self.entry_b.id}/status/",
            data='{"status": "disputed", "dispute_reason": "wrong slab"}',
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        payouts = CommissionPayout.objects.filter(company=self.company)
        self.assertEqual(payouts.count(), 1)
        self.assertEqual(payouts.get().amount, 100.00)
        self.assertEqual(payouts.get().entries_count, 1)


class SingleEntryPaidUpdatesPayoutTests(PayoutTestCase):
    def test_marking_entry_paid_stamps_month_and_creates_payout(self):
        entry = CommissionEntry.objects.filter(agent=self.agent).first()
        entry.settlement_month = None
        entry.save(update_fields=["settlement_month"])

        resp = self.client.post(
            f"/api/commission-entries/{entry.id}/status/",
            data='{"status": "paid"}',
            content_type="application/json",
            **get_jwt_headers(self.admin),
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        entry.refresh_from_db()
        self.assertIsNotNone(entry.settlement_month)

        payout = CommissionPayout.objects.get(company=self.company)
        self.assertEqual(payout.amount, entry.commission_amount)
        self.assertEqual(payout.entries_count, 1)
