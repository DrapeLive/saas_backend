from django.test import TestCase
from rest_framework import status

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_super_admin,
    create_user,
    get_jwt_headers,
)

# Tenant business-data endpoints that must never be reachable by superadmin.
TENANT_ENDPOINTS = [
    "/api/admin/agents",
    "/api/admin/agents/overview",
    "/api/admin/agents/leaderboard",
    "/api/admin/customers/",
    "/api/admin/users",
    "/api/admin/dashboard",
    "/api/business/stats",
    "/api/admin/analytics",
    "/api/commission-plans/",
    "/api/commission-entries/",
    "/api/commission-entries/summary/",
]

# Platform administration endpoints superadmin must keep.
SUPERADMIN_ENDPOINTS = [
    "/api/super-admin/companies",
    "/api/super-admin/dashboard",
]


class SuperAdminTenantIsolationTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.super_admin = create_super_admin()

    def test_superadmin_gets_403_on_all_tenant_endpoints(self):
        for url in TENANT_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.get(url, **get_jwt_headers(self.super_admin))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_keeps_platform_console(self):
        for url in SUPERADMIN_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.get(url, **get_jwt_headers(self.super_admin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_superadmin_cannot_manage_cross_company_users(self):
        other_admin = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="victim@admin.com",
        )
        resp = self.client.patch(
            f"/api/admin/users/{other_admin.id}",
            data='{"full_name": "Hacked"}',
            content_type="application/json",
            **get_jwt_headers(self.super_admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TenantRoleAccessTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.subadmin = create_user(role=RoleType.SUB_ADMIN, company=self.company)

    def test_admin_can_list_agents_and_customers(self):
        for url in ("/api/admin/agents", "/api/admin/customers/"):
            with self.subTest(url=url):
                resp = self.client.get(url, **get_jwt_headers(self.admin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_subadmin_can_access_agents_page(self):
        for url in ("/api/admin/agents", "/api/admin/agents/overview"):
            with self.subTest(url=url):
                resp = self.client.get(url, **get_jwt_headers(self.subadmin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_agent_cannot_access_admin_endpoints(self):
        agent = create_user(role=RoleType.AGENT, company=self.company)
        resp = self.client.get("/api/admin/agents", **get_jwt_headers(agent))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
