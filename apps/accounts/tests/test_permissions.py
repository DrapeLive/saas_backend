from django.test import TestCase
from django.http import HttpRequest
from unittest.mock import Mock

from apps.accounts.models import RoleType, User
from apps.accounts.permissions import (
    CanManageUsers,
    CompanyApproved,
    IsAgent,
    IsCompanyAdmin,
    IsCompanyAdminOrAbove,
    IsCompanyStaff,
    IsSelf,
    IsSuperAdmin,
)
from apps.accounts.tests.factories import create_company, create_user, create_super_admin


def make_request(user, company=None):
    request = HttpRequest()
    request.user = user
    request.company = company
    request.method = "GET"
    return request


class IsSuperAdminTests(TestCase):
    def setUp(self):
        self.perm = IsSuperAdmin()
        self.super_admin = create_super_admin()
        self.admin = create_user(
            role=RoleType.ADMIN, company=create_company(), email="admin@test.com"
        )

    def test_super_admin_has_permission(self):
        self.assertTrue(self.perm.has_permission(make_request(self.super_admin), None))

    def test_admin_has_no_permission(self):
        self.assertFalse(self.perm.has_permission(make_request(self.admin), None))


class IsCompanyAdminTests(TestCase):
    def setUp(self):
        self.perm = IsCompanyAdmin()

    def test_admin_with_company_has_permission(self):
        user = create_user(role=RoleType.ADMIN, company=create_company())
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_admin_without_company_has_no_permission(self):
        user = create_user(
            role=RoleType.ADMIN, company=None, email="nocompany@admin.com"
        )
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_super_admin_has_no_permission(self):
        user = create_super_admin()
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_agent_has_no_permission(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        self.assertFalse(self.perm.has_permission(make_request(user), None))


class IsCompanyAdminOrAboveTests(TestCase):
    def setUp(self):
        self.perm = IsCompanyAdminOrAbove()

    def test_super_admin_has_permission(self):
        self.assertTrue(self.perm.has_permission(make_request(create_super_admin()), None))

    def test_admin_has_permission(self):
        user = create_user(role=RoleType.ADMIN, company=create_company())
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_sub_admin_has_no_permission(self):
        user = create_user(
            role=RoleType.SUB_ADMIN, company=create_company(), email="sub@test.com"
        )
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_agent_has_no_permission(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        self.assertFalse(self.perm.has_permission(make_request(user), None))


class IsCompanyStaffTests(TestCase):
    def setUp(self):
        self.perm = IsCompanyStaff()

    def test_super_admin_has_permission(self):
        self.assertTrue(self.perm.has_permission(make_request(create_super_admin()), None))

    def test_admin_has_permission(self):
        user = create_user(role=RoleType.ADMIN, company=create_company())
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_sub_admin_has_permission(self):
        user = create_user(
            role=RoleType.SUB_ADMIN, company=create_company(), email="sub@test.com"
        )
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_agent_has_permission(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_customer_has_no_permission(self):
        user = create_user(
            role=RoleType.CUSTOMER, company=create_company(), email="cust@test.com"
        )
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_unauthenticated_has_no_permission(self):
        request = HttpRequest()
        request.user = Mock(is_authenticated=False)
        self.assertFalse(self.perm.has_permission(request, None))


class IsAgentTests(TestCase):
    def setUp(self):
        self.perm = IsAgent()

    def test_agent_has_permission(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_admin_has_no_permission(self):
        user = create_user(role=RoleType.ADMIN, company=create_company())
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_super_admin_has_no_permission(self):
        self.assertFalse(
            self.perm.has_permission(make_request(create_super_admin()), None)
        )


class IsSelfTests(TestCase):
    def setUp(self):
        self.perm = IsSelf()
        self.user = create_user(role=RoleType.ADMIN, company=create_company())

    def test_self_has_object_permission(self):
        self.assertTrue(self.perm.has_object_permission(None, None, self.user))

    def test_other_has_no_object_permission(self):
        other = create_user(
            role=RoleType.AGENT, company=None, email="other@test.com"
        )
        self.assertFalse(self.perm.has_object_permission(None, None, other))


class CompanyApprovedTests(TestCase):
    def setUp(self):
        self.perm = CompanyApproved()

    def test_pending_company_blocked(self):
        company = create_company(status="pending")
        user = create_user(role=RoleType.ADMIN, company=company)
        request = make_request(user, company=company)
        self.assertFalse(self.perm.has_permission(request))

    def test_trial_company_allowed(self):
        company = create_company(status="trial")
        user = create_user(role=RoleType.ADMIN, company=company)
        request = make_request(user, company=company)
        self.assertTrue(self.perm.has_permission(request))

    def test_active_company_allowed(self):
        company = create_company(status="active")
        user = create_user(role=RoleType.ADMIN, company=company)
        request = make_request(user, company=company)
        self.assertTrue(self.perm.has_permission(request))

    def test_super_admin_bypasses_pending(self):
        company = create_company(status="pending")
        user = create_super_admin()
        request = make_request(user, company=company)
        self.assertTrue(self.perm.has_permission(request))

    def test_agent_without_company_has_permission(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        request = make_request(user, company=None)
        self.assertTrue(self.perm.has_permission(request))

    def test_unauthenticated_has_no_permission(self):
        request = HttpRequest()
        request.user = Mock(is_authenticated=False)
        self.assertFalse(self.perm.has_permission(request, None))


class CanManageUsersTests(TestCase):
    def setUp(self):
        self.perm = CanManageUsers()

    def test_super_admin_can_manage(self):
        self.assertTrue(
            self.perm.has_permission(make_request(create_super_admin()), None)
        )

    def test_admin_can_manage(self):
        user = create_user(role=RoleType.ADMIN, company=create_company())
        self.assertTrue(self.perm.has_permission(make_request(user), None))

    def test_agent_cannot_manage(self):
        user = create_user(role=RoleType.AGENT, company=None, email="agent@test.com")
        self.assertFalse(self.perm.has_permission(make_request(user), None))

    def test_sub_admin_cannot_manage(self):
        user = create_user(
            role=RoleType.SUB_ADMIN, company=create_company(), email="sub@test.com"
        )
        self.assertFalse(self.perm.has_permission(make_request(user), None))
