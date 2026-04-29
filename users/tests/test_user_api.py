from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework import response, status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from stores.models import Store
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

    def test_activation_payload_includes_bootstrap_store_structure(self):
        user = services.register_user(
            username="activationstores",
            email="activationstores@example.com",
            password="pwxyz123",
        )
        store_with_subdomain = Store.objects.create(
            owner=user,
            name="Activation Store One",
            tenant_id=user.tenant_id,
            subdomain="activation-one",
        )
        store_without_subdomain = Store.objects.create(
            owner=user,
            name="Activation Store Two",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        response = self.client.get(f"/api/auth/activate/{user.activation_token}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(len(payload["stores"]), 2)

        stores_by_id = {item["id"]: item for item in payload["stores"]}
        self.assertEqual(stores_by_id[store_with_subdomain.id]["slug"], store_with_subdomain.slug)
        self.assertEqual(stores_by_id[store_with_subdomain.id]["subdomain"], "activation-one")
        self.assertEqual(stores_by_id[store_without_subdomain.id]["slug"], store_without_subdomain.slug)
        self.assertIsNone(stores_by_id[store_without_subdomain.id]["subdomain"])

        current_store = payload["current_store"]
        self.assertEqual(
            set(current_store.keys()),
            {"id", "name", "slug", "subdomain"},
        )

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
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(payload["stores"], [])
        self.assertIsNone(payload["current_store"])

    def test_superadmin_login_returns_required_auth_payload(self):
        user = User.objects.create_user(
            username="admin",
            email="superadmin@gmail.com",
            password="secret",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
            first_name="Admin",
            last_name="User",
        )
        Store.objects.create(
            owner=user,
            name="Ignored Admin Store",
            tenant_id=9999,
            subdomain="ignored-admin-store",
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "superadmin@gmail.com",
                "password": "secret",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["role"], "Super Admin")
        self.assertIsNone(payload["tenant_id"])
        self.assertEqual(payload["stores"], [])
        self.assertIsNone(payload["current_store"])

    def test_store_owner_login_payload_still_unchanged(self):
        user = User.objects.create_user(
            username="contract_owner_login",
            email="contract_owner_login@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=8101,
        )
        store = Store.objects.create(
            owner=user,
            name="Contract Owner Login Store",
            tenant_id=user.tenant_id,
            subdomain="contract-owner-login",
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "contract_owner_login@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["role"], "Store Owner")
        self.assertEqual(payload["tenant_id"], user.tenant_id)
        self.assertEqual(len(payload["stores"]), 1)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "contract-owner-login")

    def test_login_payload_includes_current_store_slug_and_subdomain(self):
        user = User.objects.create_user(
            username="storelogin",
            email="storelogin@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=5001,
        )
        store = Store.objects.create(
            owner=user,
            name="Beauty Login Store",
            tenant_id=user.tenant_id,
            subdomain="beauty-login",
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "storelogin@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(len(payload["stores"]), 1)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "beauty-login")

    def test_login_payload_does_not_mirror_slug_into_missing_subdomain(self):
        user = User.objects.create_user(
            username="slugonly",
            email="slugonly@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=5002,
        )
        store = Store.objects.create(
            owner=user,
            name="Slug Only Store",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "slugonly@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertIsNone(payload["current_store"]["subdomain"])

    def test_login_payload_with_multiple_owned_stores_returns_all_with_mixed_subdomains(self):
        user = User.objects.create_user(
            username="multistore_login",
            email="multistore_login@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=5004,
        )
        store_with_subdomain = Store.objects.create(
            owner=user,
            name="Multi Store A",
            tenant_id=user.tenant_id,
            subdomain="multi-store-a",
        )
        store_without_subdomain = Store.objects.create(
            owner=user,
            name="Multi Store B",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "multistore_login@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(len(payload["stores"]), 2)

        stores_by_id = {item["id"]: item for item in payload["stores"]}
        self.assertEqual(stores_by_id[store_with_subdomain.id]["slug"], store_with_subdomain.slug)
        self.assertEqual(stores_by_id[store_with_subdomain.id]["subdomain"], "multi-store-a")
        self.assertEqual(stores_by_id[store_without_subdomain.id]["slug"], store_without_subdomain.slug)
        self.assertIsNone(stores_by_id[store_without_subdomain.id]["subdomain"])

        current_store = payload["current_store"]
        self.assertEqual(
            set(current_store.keys()),
            {"id", "name", "slug", "subdomain"},
        )
        self.assertEqual(current_store["id"], store_with_subdomain.id)

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
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(payload["stores"], [])
        self.assertIsNone(payload["current_store"])

    def test_superadmin_me_returns_required_identity_payload(self):
        user = User.objects.create_user(
            username="admin",
            email="superadmin@gmail.com",
            password="secret",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
            first_name="Admin",
            last_name="User",
        )
        Store.objects.create(
            owner=user,
            name="Ignored Admin Store",
            tenant_id=9999,
            subdomain="ignored-admin-store",
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["username"], "admin")
        self.assertEqual(payload["email"], "superadmin@gmail.com")
        self.assertEqual(payload["role"], "Super Admin")
        self.assertIsNone(payload["tenant_id"])
        self.assertTrue(payload["is_active"])
        self.assertEqual(payload["display_name"], "Admin User")
        self.assertIn("created_at", payload)
        self.assertIn("updated_at", payload)
        self.assertEqual(payload["stores"], [])
        self.assertIsNone(payload["current_store"])
        self.assertNotIn("access", payload)
        self.assertNotIn("refresh", payload)

    def test_superadmin_token_refresh_returns_new_access_token(self):
        user = User.objects.create_user(
            username="refreshadmin",
            email="superadmin@gmail.com",
            password="secret",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
        )
        refresh = RefreshToken.for_user(user)

        response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("access", payload)
        self.assertNotIn("tenant_id", payload)

    def test_store_owner_me_payload_still_unchanged(self):
        user = User.objects.create_user(
            username="contract_owner_me",
            email="contract_owner_me@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=8102,
            first_name="Contract",
            last_name="Owner",
        )
        store = Store.objects.create(
            owner=user,
            name="Contract Owner Me Store",
            tenant_id=user.tenant_id,
            subdomain="contract-owner-me",
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["user_id"], user.id)
        self.assertEqual(payload["username"], "contract_owner_me")
        self.assertEqual(payload["email"], "contract_owner_me@example.com")
        self.assertEqual(payload["role"], "Store Owner")
        self.assertEqual(payload["tenant_id"], user.tenant_id)
        self.assertTrue(payload["is_active"])
        self.assertEqual(payload["display_name"], "Contract Owner")
        self.assertIn("created_at", payload)
        self.assertIn("updated_at", payload)
        self.assertNotIn("access", payload)
        self.assertNotIn("refresh", payload)
        self.assertEqual(len(payload["stores"]), 1)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "contract-owner-me")

    def test_me_includes_current_store_slug_and_subdomain(self):
        user = User.objects.create_user(
            username="storeme",
            email="storeme@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=5003,
        )
        store = Store.objects.create(
            owner=user,
            name="Store Me",
            tenant_id=user.tenant_id,
            subdomain="store-me-live",
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(len(payload["stores"]), 1)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "store-me-live")

    def test_me_with_multiple_owned_stores_returns_bootstrap_structure(self):
        user = User.objects.create_user(
            username="multistore_me",
            email="multistore_me@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=5005,
        )
        store_with_subdomain = Store.objects.create(
            owner=user,
            name="Me Store A",
            tenant_id=user.tenant_id,
            subdomain="me-store-a",
        )
        store_without_subdomain = Store.objects.create(
            owner=user,
            name="Me Store B",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        response = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=self._auth_header(user),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("stores", payload)
        self.assertIn("current_store", payload)
        self.assertEqual(len(payload["stores"]), 2)

        stores_by_id = {item["id"]: item for item in payload["stores"]}
        self.assertEqual(stores_by_id[store_with_subdomain.id]["slug"], store_with_subdomain.slug)
        self.assertEqual(stores_by_id[store_with_subdomain.id]["subdomain"], "me-store-a")
        self.assertEqual(stores_by_id[store_without_subdomain.id]["slug"], store_without_subdomain.slug)
        self.assertIsNone(stores_by_id[store_without_subdomain.id]["subdomain"])
        self.assertEqual(payload["current_store"]["id"], store_with_subdomain.id)

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
        self.assertEqual(payload["stores"], [])
        self.assertIsNone(payload["current_store"])

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
    def test_login_bootstrap_reflects_latest_subdomain_after_store_update(self):
        user = User.objects.create_user(
            username="bootstrap_refresh_login",
            email="bootstrap_refresh_login@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=7001,
        )
        store = Store.objects.create(
            owner=user,
            name="Bootstrap Refresh Store",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        authenticated_client = APIClient()
        authenticated_client.credentials(HTTP_AUTHORIZATION=self._auth_header(user))

        patch_response = authenticated_client.patch(
            f"/api/stores/{store.id}/subdomain/",
            {"subdomain": "fresh-bootstrap-subdomain"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "email": "bootstrap_refresh_login@example.com",
                "password": "StrongPass123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)

        payload = self._payload(login_response)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "fresh-bootstrap-subdomain")


    def test_me_bootstrap_reflects_latest_subdomain_after_store_update(self):
        user = User.objects.create_user(
            username="bootstrap_refresh_me",
            email="bootstrap_refresh_me@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=7002,
        )
        store = Store.objects.create(
            owner=user,
            name="Bootstrap Me Store",
            tenant_id=user.tenant_id,
            subdomain=None,
        )

        authenticated_client = APIClient()
        authenticated_client.credentials(HTTP_AUTHORIZATION=self._auth_header(user))

        patch_response = authenticated_client.patch(
            f"/api/stores/{store.id}/subdomain/",
            {"subdomain": "fresh-me-subdomain"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        me_response = authenticated_client.get("/api/auth/me/")
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)

        payload = self._payload(me_response)
        self.assertEqual(payload["current_store"]["id"], store.id)
        self.assertEqual(payload["current_store"]["slug"], store.slug)
        self.assertEqual(payload["current_store"]["subdomain"], "fresh-me-subdomain")