from django.http import HttpRequest
from django.test import TestCase

from apps.accounts.middleware import CompanyScopeMiddleware
from apps.accounts.tests.factories import create_company, create_user


class CompanyScopeMiddlewareTests(TestCase):
    def setUp(self):
        self.middleware = CompanyScopeMiddleware(lambda req: None)

    def test_sets_request_company_none_for_anonymous(self):
        request = HttpRequest()
        request.user = type("AnonymousUser", (), {"is_authenticated": False})()
        self.middleware(request)
        self.assertIsNone(request.company)

    def test_sets_request_company_none_when_not_set(self):
        request = HttpRequest()
        self.middleware(request)
        self.assertTrue(hasattr(request, "company"))
