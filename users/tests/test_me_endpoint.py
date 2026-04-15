from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User


class MeEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _auth_header(self, user):
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_me_with_valid_token_store_owner_returns_identity(self):
        user = User.objects.create_user(
            username="omarMas",
            email="omarmas@gmail.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=1,
            first_name="Omar",
            last_name="Mas",
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user_id"], user.id)
        self.assertEqual(response.data["username"], "omarMas")
        self.assertEqual(response.data["email"], "omarmas@gmail.com")
        self.assertEqual(response.data["role"], "Store Owner")
        self.assertEqual(response.data["tenant_id"], 1)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["display_name"], "Omar Mas")
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

    def test_me_with_valid_token_super_admin_works_with_null_tenant(self):
        user = User.objects.create_user(
            username="rootAdmin",
            email="root@example.com",
            password="StrongPass123!",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user_id"], user.id)
        self.assertEqual(response.data["role"], "Super Admin")
        self.assertIsNone(response.data["tenant_id"])
        self.assertEqual(response.data["display_name"], "rootAdmin")

    def test_me_missing_token_returns_401(self):
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.data)

    def test_me_invalid_token_returns_401(self):
        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())
