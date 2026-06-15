from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory

from apps.accounts.models import RoleType, User
from apps.accounts.views import AuthViewSet
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    get_jwt_headers,
)


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = AuthViewSet.as_view({"post": "password_change"})
        self.company = create_company()
        self.user = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="user@test.com",
            password="OldPass@123",
        )
        self.headers = get_jwt_headers(self.user)

    def test_password_change_success(self):
        response = self.view(
            self.factory.post("/api/auth/password/change", {
                "old_password": "OldPass@123",
                "new_password": "NewPass@456",
            }, format="json", **self.headers)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass@456"))

    def test_password_change_wrong_old_password(self):
        response = self.view(
            self.factory.post("/api/auth/password/change", {
                "old_password": "WrongPass@999",
                "new_password": "NewPass@456",
            }, format="json", **self.headers)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_weak_new_password(self):
        response = self.view(
            self.factory.post("/api/auth/password/change", {
                "old_password": "OldPass@123",
                "new_password": "123",
            }, format="json", **self.headers)
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_change_requires_auth(self):
        response = self.view(
            self.factory.post("/api/auth/password/change", {
                "old_password": "OldPass@123",
                "new_password": "NewPass@456",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.reset_view = AuthViewSet.as_view({"post": "password_reset"})
        self.confirm_view = AuthViewSet.as_view({"post": "password_reset_confirm"})
        self.company = create_company()
        self.user = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="reset@test.com",
            password="OldPass@123",
        )

    def test_password_reset_returns_uid_and_token(self):
        response = self.reset_view(
            self.factory.post("/api/auth/password/reset", {
                "email": "reset@test.com",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("uid", response.data)
        self.assertIn("token", response.data)
        self.assertIsNotNone(response.data["uid"])
        self.assertIsNotNone(response.data["token"])

    def test_password_reset_nonexistent_email(self):
        response = self.reset_view(
            self.factory.post("/api/auth/password/reset", {
                "email": "nobody@test.com",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_password_reset_confirm_success(self):
        reset_response = self.reset_view(
            self.factory.post("/api/auth/password/reset", {
                "email": "reset@test.com",
            }, format="json")
        )
        uid = reset_response.data["uid"]
        token = reset_response.data["token"]

        confirm_response = self.confirm_view(
            self.factory.post("/api/auth/password/reset/confirm", {
                "uid": uid,
                "token": token,
                "new_password": "NewPass@789",
            }, format="json")
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPass@789"))

    def test_password_reset_confirm_invalid_token(self):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.confirm_view(
            self.factory.post("/api/auth/password/reset/confirm", {
                "uid": uid,
                "token": "invalid-token",
                "new_password": "NewPass@789",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_confirm_invalid_uid(self):
        response = self.confirm_view(
            self.factory.post("/api/auth/password/reset/confirm", {
                "uid": "invalid-uid",
                "token": "some-token",
                "new_password": "NewPass@789",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_reset_confirm_weak_password(self):
        reset_response = self.reset_view(
            self.factory.post("/api/auth/password/reset", {
                "email": "reset@test.com",
            }, format="json")
        )
        uid = reset_response.data["uid"]
        token = reset_response.data["token"]

        response = self.confirm_view(
            self.factory.post("/api/auth/password/reset/confirm", {
                "uid": uid,
                "token": token,
                "new_password": "123",
            }, format="json")
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
