from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework import response, status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users import services
from users.models import User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class UserApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @staticmethod
    def _payload(response):
        return response.json()

    def _auth_header(self, user):
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    # ---------------------------------
    # Registration
    # ---------------------------------

    def test_store_owner_can_self_register(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "owner1",
                "email": "owner1@example.com",
                "password": "StrongPass123!",
                "role": "Store Owner",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="owner1@example.com")
        self.assertEqual(user.role, "Store Owner")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.tenant_id, user.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/api/auth/activate/", mail.outbox[0].body)

        user = User.objects.get(email="owner1@example.com")
        self.assertEqual(user.role, "Store Owner")
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.tenant_id, user.id)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/api/auth/activate/", mail.outbox[0].body)

    def test_register_rejects_client_supplied_tenant_id(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "mallory",
                "email": "mallory@example.com",
                "password": "StrongPass123!",
                "role": "Store Owner",
                "tenant_id": 999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("tenant_id", payload)
        self.assertFalse(User.objects.filter(email="mallory@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_register_rejects_super_admin_role(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "username": "rootish",
                "email": "rootish@example.com",
                "password": "StrongPass123!",
                "role": "Super Admin",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("role", payload)
        self.assertFalse(User.objects.filter(email="rootish@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    # ---------------------------------
    # Login / activation
    # ---------------------------------

    def test_login_blocked_before_activation(self):
        user = User.objects.create(
            username="bob",
            email="bob@example.com",
            is_active=False,
            role="Store Owner",
            tenant_id=1,
        )
        user.set_password("pw12345")
        user.save()

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "bob@example.com",
                "password": "pw12345",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("Email not verified", payload["detail"])

    def test_login_invalid_credentials_returns_401(self):
        user = User.objects.create(
            username="wrongpass",
            email="wrongpass@example.com",
            is_active=True,
            role="Store Owner",
            tenant_id=1,
        )
        user.set_password("CorrectPass123!")
        user.save()

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "wrongpass@example.com",
                "password": "WrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("Invalid credentials", payload["detail"])

    def test_activation_link_activates_and_returns_tokens(self):
        user = services.register_user(
            username="carol",
            email="carol@example.com",
            password="pwxyz123",
        )

        token = user.activation_token

        response = self.client.get(f"/api/auth/activate/{token}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("Account activated successfully", payload["detail"])
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["role"], "Store Owner")
        self.assertEqual(payload["tenant_id"], user.id)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertIsNone(user.activation_token)

    def test_login_after_activation_returns_tokens_and_identity_fields(self):
        user = services.register_user(
            username="activeuser",
            email="active@example.com",
            password="pwxyz123",
        )
        user.is_active = True
        user.activation_token = None
        user.save(update_fields=["is_active", "activation_token"])

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "active@example.com",
                "password": "pwxyz123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["role"], "Store Owner")
        self.assertEqual(payload["tenant_id"], user.id)

    # ---------------------------------
    # Me endpoint
    # ---------------------------------

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
        payload = self._payload(response)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["username"], "omarMas")
        self.assertEqual(payload["email"], "omarmas@gmail.com")
        self.assertEqual(payload["role"], "Store Owner")
        self.assertEqual(payload["tenant_id"], 1)
        self.assertTrue(payload["is_active"])
        self.assertEqual(payload["display_name"], "Omar Mas")
        self.assertIn("created_at", payload)
        self.assertIn("updated_at", payload)
        self.assertNotIn("access", payload)
        self.assertNotIn("refresh", payload)

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
        payload = self._payload(response)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["role"], "Super Admin")
        self.assertIsNone(payload["tenant_id"])
        self.assertEqual(payload["display_name"], "rootAdmin")

    def test_me_missing_token_returns_401(self):
        response = self.client.get("/api/auth/me/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn(
            "Authentication credentials were not provided.",
            payload["detail"],
        )

    def test_me_invalid_token_returns_401(self):
        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("Invalid token", payload["detail"])

    # ---------------------------------
    # JWT middleware behavior
    # ---------------------------------

    def test_missing_tenant_for_non_superadmin_returns_403(self):
        user = User.objects.create(
            username="no_tenant",
            email="nont@example.com",
            role="Store Owner",
            is_active=True,
            tenant_id=None,
        )
        user.set_password("pw12345")
        user.save()

        response = self.client.get(
            "/api/auth/register/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("tenant_id missing", payload["detail"])

    def test_super_admin_without_tenant_allowed_through_middleware(self):
        user = User.objects.create(
            username="sa",
            email="sa@example.com",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
        )
        user.set_password("pw12345")
        user.save()

        response = self.client.get(
            "/api/auth/register/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        # Middleware allows request through; endpoint itself does not support GET.
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_405_METHOD_NOT_ALLOWED])

    def test_inactive_user_token_rejected_by_middleware(self):
        user = User.objects.create(
            username="inactive",
            email="inactive@example.com",
            role="Store Owner",
            is_active=False,
            tenant_id=10,
        )
        user.set_password("StrongPass123!")
        user.save()

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertTrue(isinstance(payload["detail"], str))

    # ---------------------------------
    # Super Admin bootstrap path
    # ---------------------------------

    def test_backend_controlled_superadmin_creation_command_works(self):
        out = StringIO()

        call_command(
            "bootstrap_superadmin",
            password="StrongSuperAdmin123!",
            stdout=out,
        )

        user = User.objects.get(email="superadmin@gmail.com")
        self.assertEqual(user.role, "Super Admin")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertIsNone(user.tenant_id)
        self.assertIn("Super Admin created successfully", out.getvalue())

    def test_superadmin_can_login_after_backend_creation(self):
        call_command(
            "bootstrap_superadmin",
            password="StrongSuperAdmin123!",
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "superadmin@gmail.com",
                "password": "StrongSuperAdmin123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["role"], "Super Admin")
        self.assertIsNone(payload["tenant_id"])