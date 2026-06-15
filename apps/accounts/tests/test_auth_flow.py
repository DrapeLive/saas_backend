from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleType, User
from apps.accounts.views import AuthViewSet, LoginView, SignupView
from apps.accounts.tests.factories import (
    create_company,
    create_super_admin,
    create_user,
    get_jwt_headers,
)


class SignupTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = SignupView.as_view({"post": "create"})
        self.valid_data = {
            "email": "admin@newcompany.com",
            "password": "StrongPass@123",
            "full_name": "New Admin",
            "phone": "9876543210",
            "company_name": "New Company",
            "company_slug": "new-company",
        }

    def test_signup_creates_company_and_admin(self):
        response = self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(email="admin@newcompany.com")
        self.assertEqual(user.role, RoleType.ADMIN)
        self.assertIsNotNone(user.company)
        self.assertEqual(user.company.status, "pending")
        self.assertEqual(user.company.name, "New Company")

    def test_signup_returns_jwt_pair(self):
        response = self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIsNotNone(response.data["access"])
        self.assertIsNotNone(response.data["refresh"])

    def test_signup_returns_user_data(self):
        response = self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["email"], "admin@newcompany.com")
        self.assertEqual(response.data["user"]["role"], "admin")
        self.assertEqual(response.data["user"]["full_name"], "New Admin")

    def test_signup_duplicate_email_rejected(self):
        self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        response = self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_duplicate_slug_rejected(self):
        self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        dup = dict(self.valid_data)
        dup["email"] = "other@newcompany.com"
        dup["company_slug"] = "new-company"
        response = self.view(self.factory.post("/api/auth/signup", dup, format="json"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_missing_required_fields(self):
        response = self.view(self.factory.post("/api/auth/signup", {}, format="json"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_weak_password_rejected(self):
        data = dict(self.valid_data)
        data["password"] = "123"
        response = self.view(self.factory.post("/api/auth/signup", data, format="json"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_signup_jwt_has_claims(self):
        response = self.view(self.factory.post("/api/auth/signup", self.valid_data, format="json"))
        token = RefreshToken(response.data["refresh"])
        self.assertEqual(token["role"], "admin")
        self.assertIsNotNone(token["company_id"])
        self.assertFalse(token["is_super_admin"])


class LoginTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = LoginView.as_view()
        self.company = create_company()
        self.user = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="admin@test.com",
            password="Test@12345678",
        )

    def test_login_success(self):
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "Test@12345678",
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)

    def test_login_returns_user_data(self):
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "Test@12345678",
        }, format="json"))
        self.assertEqual(response.data["user"]["email"], "admin@test.com")
        self.assertEqual(response.data["user"]["role"], "admin")

    def test_login_wrong_password(self):
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "WrongPass@123",
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_email(self):
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "nobody@test.com",
            "password": "Test@12345678",
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_disabled_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "Test@12345678",
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_updates_ip_and_device(self):
        self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "Test@12345678",
        }, format="json", **{"REMOTE_ADDR": "192.168.1.1", "HTTP_USER_AGENT": "TestAgent/1.0"}))
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_login_ip, "192.168.1.1")
        self.assertEqual(self.user.last_login_device, "TestAgent/1.0")

    def test_login_jwt_has_claims(self):
        response = self.view(self.factory.post("/api/auth/login", {
            "email": "admin@test.com",
            "password": "Test@12345678",
        }, format="json"))
        token = RefreshToken(response.data["refresh"])
        self.assertEqual(token["role"], "admin")
        self.assertIsNotNone(token["company_id"])
        self.assertFalse(token["is_super_admin"])


class RefreshTests(TestCase):
    def setUp(self):
        from rest_framework_simplejwt.views import TokenRefreshView
        self.factory = APIRequestFactory()
        self.view = TokenRefreshView.as_view()
        self.user = create_user(role=RoleType.ADMIN, company=create_company())
        self.refresh = RefreshToken.for_user(self.user)
        self.refresh["role"] = self.user.role
        self.refresh["company_id"] = str(self.user.company_id)
        self.refresh["is_super_admin"] = False

    def test_refresh_success(self):
        response = self.view(self.factory.post("/api/auth/refresh", {
            "refresh": str(self.refresh),
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_refresh_rotates_token(self):
        old_refresh = str(self.refresh)
        response = self.view(self.factory.post("/api/auth/refresh", {
            "refresh": old_refresh,
        }, format="json"))
        self.assertNotEqual(str(response.data["refresh"]), old_refresh)

    def test_refresh_blacklisted_token_rejected(self):
        self.refresh.blacklist()
        response = self.view(self.factory.post("/api/auth/refresh", {
            "refresh": str(self.refresh),
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_invalid_token(self):
        response = self.view(self.factory.post("/api/auth/refresh", {
            "refresh": "invalid-token-here",
        }, format="json"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LogoutTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AuthViewSet.as_view({"post": "logout"})
        self.user = create_user(role=RoleType.ADMIN, company=create_company())
        self.headers = get_jwt_headers(self.user)

    def test_logout_blacklists_token(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.view(
            self.factory.post("/api/auth/logout", {"refresh": str(refresh)},
                              format="json", **self.headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        with self.assertRaises(Exception):
            RefreshToken(str(refresh)).check_blacklist()

    def test_logout_without_refresh_token(self):
        response = self.view(
            self.factory.post("/api/auth/logout", {}, format="json", **self.headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_requires_auth(self):
        response = self.view(
            self.factory.post("/api/auth/logout", {}, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
