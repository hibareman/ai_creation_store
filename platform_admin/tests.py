from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from orders.models import Order
from platform_admin.models import PlatformAdminSettings
from products.models import Product
from stores.models import Store
from users.models import User


STORE_SUMMARY_KEYS = {
    "id",
    "name",
    "owner_name",
    "owner_email",
    "status",
    "products_count",
    "orders_count",
    "revenue_total",
    "created_at",
    "updated_at",
}

USER_SUMMARY_KEYS = {
    "id",
    "full_name",
    "email",
    "role",
    "stores_count",
    "status",
    "created_at",
}

SETTINGS_KEYS = {
    "support_email",
    "default_currency",
    "allow_public_registration",
    "require_store_approval",
    "maintenance_mode",
}

DEFAULT_SETTINGS = {
    "support_email": "support@example.com",
    "default_currency": "USD",
    "allow_public_registration": True,
    "require_store_approval": True,
    "maintenance_mode": False,
}


class PlatformAdminApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.super_admin = User.objects.create_user(
            username="superadmin",
            email="superadmin@gmail.com",
            password="StrongPass123!",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
        )
        self.store_owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=1001,
            first_name="Ahmed",
            last_name="Al-Farsi",
        )
        self.other_owner = User.objects.create_user(
            username="otherowner",
            email="other@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=True,
            tenant_id=1002,
            first_name="Hiba",
            last_name="Reman",
        )

    def _auth_header(self, user):
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def _as_super_admin(self):
        self.client.credentials(HTTP_AUTHORIZATION=self._auth_header(self.super_admin))

    def _as_store_owner(self):
        self.client.credentials(HTTP_AUTHORIZATION=self._auth_header(self.store_owner))

    def _create_store(self, *, name, owner=None, status="setup", subdomain=None):
        owner = owner or self.store_owner
        return Store.objects.create(
            owner=owner,
            name=name,
            status=status,
            tenant_id=owner.tenant_id,
            subdomain=subdomain,
        )

    def _create_product(self, store, sku):
        return Product.objects.create(
            store=store,
            tenant_id=store.tenant_id,
            name=f"Product {sku}",
            description="",
            price=Decimal("10.00"),
            sku=sku,
            status="active",
        )

    def _create_order(self, store, total_price):
        return Order.objects.create(
            store=store,
            tenant_id=store.tenant_id,
            total_price=Decimal(total_price),
        )

    def _seed_store_with_activity(self):
        store = self._create_store(
            name="Elegance Fashion",
            status="active",
            subdomain="elegance-fashion",
        )
        self._create_product(store, "SKU-1")
        self._create_product(store, "SKU-2")
        self._create_order(store, "100.00")
        self._create_order(store, "25.50")
        return store

    def _assert_store_summary_shape(self, item):
        self.assertEqual(set(item.keys()), STORE_SUMMARY_KEYS)
        self.assertIsInstance(item["id"], int)
        self.assertIsInstance(item["name"], str)
        self.assertIsInstance(item["owner_name"], str)
        self.assertIsInstance(item["owner_email"], str)
        self.assertIn(item["status"], {"active", "pending", "suspended"})
        self.assertIsInstance(item["products_count"], int)
        self.assertIsInstance(item["orders_count"], int)
        self.assertIsInstance(item["revenue_total"], (int, float))
        self.assertIn("T", item["created_at"])
        self.assertIn("T", item["updated_at"])

    def _assert_user_summary_shape(self, item):
        self.assertEqual(set(item.keys()), USER_SUMMARY_KEYS)
        self.assertIsInstance(item["id"], int)
        self.assertIsInstance(item["full_name"], str)
        self.assertIsInstance(item["email"], str)
        self.assertIsInstance(item["role"], str)
        self.assertIsInstance(item["stores_count"], int)
        self.assertIn(item["status"], {"active", "suspended"})
        self.assertIn("T", item["created_at"])

    def _assert_settings_response_shape(self, payload):
        self.assertEqual(set(payload.keys()), {"settings"})
        self.assertEqual(set(payload["settings"].keys()), SETTINGS_KEYS)
        self.assertIsInstance(payload["settings"]["support_email"], str)
        self.assertIsInstance(payload["settings"]["default_currency"], str)
        self.assertIsInstance(payload["settings"]["allow_public_registration"], bool)
        self.assertIsInstance(payload["settings"]["require_store_approval"], bool)
        self.assertIsInstance(payload["settings"]["maintenance_mode"], bool)

    # Dashboard

    def test_super_admin_can_get_dashboard_response_sections(self):
        self._seed_store_with_activity()
        self._as_super_admin()

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"stats", "store_status", "recent_stores"})

    def test_dashboard_stats_numbers_are_correct(self):
        first_store = self._seed_store_with_activity()
        second_store = self._create_store(name="Second Store", status="setup")
        self._create_order(second_store, "50.00")
        inactive_user = User.objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=False,
            tenant_id=1003,
        )
        self.assertFalse(inactive_user.is_active)
        self._as_super_admin()

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stats = response.json()["stats"]
        self.assertEqual(stats["total_stores"], 2)
        self.assertEqual(stats["active_users"], 3)
        self.assertEqual(stats["total_orders"], 3)
        self.assertEqual(stats["platform_revenue"], 175.5)
        self.assertEqual(first_store.orders.count(), 2)

    def test_dashboard_store_status_mapping_is_correct(self):
        self._create_store(name="Active Store", status="active")
        self._create_store(name="Setup Store", status="setup")
        self._create_store(name="Draft Store", status="draft")
        self._create_store(name="Inactive Store", status="inactive")
        self._as_super_admin()

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["store_status"],
            {"active": 1, "pending": 2, "suspended": 1},
        )

    def test_dashboard_recent_stores_uses_admin_store_summary_shape(self):
        self._seed_store_with_activity()
        self._as_super_admin()

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recent_stores = response.json()["recent_stores"]
        self.assertEqual(len(recent_stores), 1)
        self._assert_store_summary_shape(recent_stores[0])
        self.assertEqual(recent_stores[0]["owner_name"], "Ahmed Al-Farsi")
        self.assertEqual(recent_stores[0]["owner_email"], "owner@example.com")
        self.assertEqual(recent_stores[0]["products_count"], 2)
        self.assertEqual(recent_stores[0]["orders_count"], 2)
        self.assertEqual(recent_stores[0]["revenue_total"], 125.5)

    def test_dashboard_store_owner_gets_403(self):
        self._as_store_owner()

        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_dashboard_missing_token_gets_401(self):
        response = self.client.get("/api/admin/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    # Stores list

    def test_super_admin_can_get_stores_list_with_items(self):
        self._seed_store_with_activity()
        self._as_super_admin()

        response = self.client.get("/api/admin/stores/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"items"})
        self.assertEqual(len(payload["items"]), 1)

    def test_stores_list_item_shape_exactly_matches_contract(self):
        self._seed_store_with_activity()
        self._as_super_admin()

        response = self.client.get("/api/admin/stores/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_store_summary_shape(response.json()["items"][0])

    def test_stores_list_search_works_by_store_name(self):
        self._create_store(name="Elegance Fashion", status="active")
        self._create_store(name="Tech Hub", owner=self.other_owner, status="setup")
        self._as_super_admin()

        response = self.client.get("/api/admin/stores/", {"search": "elegance"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Elegance Fashion")

    def test_stores_list_search_works_by_owner_email(self):
        self._create_store(name="Elegance Fashion", status="active")
        self._create_store(name="Tech Hub", owner=self.other_owner, status="setup")
        self._as_super_admin()

        response = self.client.get("/api/admin/stores/", {"search": "other@example.com"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["owner_email"], "other@example.com")

    def test_stores_list_store_owner_gets_403(self):
        self._as_store_owner()

        response = self.client.get("/api/admin/stores/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_stores_list_missing_token_gets_401(self):
        response = self.client.get("/api/admin/stores/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    # Users list

    def test_super_admin_can_get_users_list(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_users_list_response_shape_is_items_only(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.json().keys()), {"items"})

    def test_users_list_item_shape_exactly_matches_contract(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_user_summary_shape(response.json()["items"][0])

    def test_users_list_role_mapping_for_super_admin_and_store_owner(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        users_by_email = {item["email"]: item for item in response.json()["items"]}
        self.assertEqual(users_by_email["superadmin@gmail.com"]["role"], "super_admin")
        self.assertEqual(users_by_email["owner@example.com"]["role"], "store_owner")

    def test_users_list_stores_count_is_correct_for_store_owner(self):
        self._create_store(name="Owner Store One", status="active")
        self._create_store(name="Owner Store Two", status="setup")
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        users_by_email = {item["email"]: item for item in response.json()["items"]}
        self.assertEqual(users_by_email["owner@example.com"]["stores_count"], 2)
        self.assertEqual(users_by_email["superadmin@gmail.com"]["stores_count"], 0)

    def test_users_list_status_is_active_for_active_user(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/", {"search": "owner@example.com"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["items"][0]["status"], "active")

    def test_users_list_inactive_user_status_is_suspended(self):
        User.objects.create_user(
            username="inactive_owner",
            email="inactive_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
            is_active=False,
            tenant_id=1003,
        )
        self._as_super_admin()

        response = self.client.get("/api/admin/users/", {"search": "inactive_owner@example.com"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "suspended")

    def test_users_list_search_works_by_email(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/", {"search": "other@example.com"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["email"], "other@example.com")

    def test_users_list_search_works_by_username(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/", {"search": "otherowner"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["email"], "other@example.com")

    def test_users_list_search_works_by_first_name_or_last_name(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/", {"search": "Reman"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["full_name"], "Hiba Reman")

    def test_users_list_store_owner_gets_403(self):
        self._as_store_owner()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_users_list_missing_token_gets_401(self):
        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_users_list_invalid_token_gets_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_users_list_does_not_expose_sensitive_or_internal_fields(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/users/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.json()["items"][0]
        self.assertEqual(set(item.keys()), USER_SUMMARY_KEYS)
        for forbidden_field in [
            "password",
            "access",
            "refresh",
            "token",
            "tenant_id",
            "activation_token",
            "is_superuser",
            "is_staff",
        ]:
            self.assertNotIn(forbidden_field, item)

    # Platform settings

    def test_super_admin_can_get_platform_settings_with_exact_shape(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/json")
        self._assert_settings_response_shape(response.json())

    def test_platform_settings_get_returns_defaults_when_row_does_not_exist(self):
        self.assertFalse(PlatformAdminSettings.objects.exists())
        self._as_super_admin()

        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"settings": DEFAULT_SETTINGS})
        self.assertTrue(PlatformAdminSettings.objects.exists())

    def test_platform_settings_patch_all_settings_returns_updated_values(self):
        self._as_super_admin()
        settings_payload = {
            "support_email": "help@example.com",
            "default_currency": "EUR",
            "allow_public_registration": False,
            "require_store_approval": False,
            "maintenance_mode": True,
        }

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": settings_payload},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"settings": settings_payload})

    def test_platform_settings_patch_supports_partial_update_without_resetting_fields(self):
        PlatformAdminSettings.objects.create(
            support_email="support@old.example.com",
            default_currency="SAR",
            allow_public_registration=False,
            require_store_approval=True,
            maintenance_mode=False,
        )
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"maintenance_mode": True}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["settings"],
            {
                "support_email": "support@old.example.com",
                "default_currency": "SAR",
                "allow_public_registration": False,
                "require_store_approval": True,
                "maintenance_mode": True,
            },
        )

    def test_platform_settings_patch_persists_across_subsequent_get(self):
        self._as_super_admin()
        settings_payload = {
            "support_email": "ops@example.com",
            "default_currency": "GBP",
            "allow_public_registration": False,
            "require_store_approval": True,
            "maintenance_mode": True,
        }

        patch_response = self.client.patch(
            "/api/admin/settings/",
            {"settings": settings_payload},
            format="json",
        )
        get_response = self.client.get("/api/admin/settings/")

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.json(), {"settings": settings_payload})

    def test_platform_settings_patch_invalid_support_email_returns_400(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"support_email": "not-an-email"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_platform_settings_patch_invalid_default_currency_returns_400(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"default_currency": "usd"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_platform_settings_patch_missing_settings_wrapper_returns_400(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"support_email": "support@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_platform_settings_patch_empty_settings_object_returns_200_unchanged(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"settings": DEFAULT_SETTINGS})

    def test_platform_settings_patch_unknown_field_returns_400(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"unknown_setting": True}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_platform_settings_get_store_owner_gets_403(self):
        self._as_store_owner()

        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_platform_settings_patch_store_owner_gets_403(self):
        self._as_store_owner()

        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"maintenance_mode": True}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_platform_settings_get_missing_token_gets_401(self):
        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_platform_settings_patch_missing_token_gets_401(self):
        response = self.client.patch(
            "/api/admin/settings/",
            {"settings": {"maintenance_mode": True}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_platform_settings_invalid_token_gets_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")

        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_platform_settings_response_does_not_expose_internal_fields(self):
        self._as_super_admin()

        response = self.client.get("/api/admin/settings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings_payload = response.json()["settings"]
        self.assertEqual(set(settings_payload.keys()), SETTINGS_KEYS)
        for forbidden_field in ["id", "created_at", "updated_at"]:
            self.assertNotIn(forbidden_field, settings_payload)

    # Store status patch

    def test_super_admin_can_set_status_active_and_backend_status_becomes_active(self):
        store = self._create_store(name="Patch Active", status="setup")
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "active"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        store.refresh_from_db()
        self.assertEqual(store.status, "active")

    def test_super_admin_can_set_status_pending_and_backend_status_becomes_setup(self):
        store = self._create_store(name="Patch Pending", status="active")
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "pending"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        store.refresh_from_db()
        self.assertEqual(store.status, "setup")

    def test_super_admin_can_set_status_suspended_and_backend_status_becomes_inactive(self):
        store = self._create_store(name="Patch Suspended", status="active")
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "suspended"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        store.refresh_from_db()
        self.assertEqual(store.status, "inactive")

    def test_store_status_patch_response_returns_updated_store_summary(self):
        store = self._seed_store_with_activity()
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "suspended"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(set(payload.keys()), {"store"})
        self._assert_store_summary_shape(payload["store"])
        self.assertEqual(payload["store"]["status"], "suspended")
        self.assertEqual(payload["store"]["products_count"], 2)
        self.assertEqual(payload["store"]["orders_count"], 2)
        self.assertEqual(payload["store"]["revenue_total"], 125.5)

    def test_store_status_patch_invalid_status_returns_400(self):
        store = self._create_store(name="Patch Invalid", status="active")
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "archived"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.json().keys()), {"detail"})

    def test_store_status_patch_nonexistent_store_returns_404(self):
        self._as_super_admin()

        response = self.client.patch(
            "/api/admin/stores/999999/status/",
            {"status": "active"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("detail", response.json())

    def test_store_status_patch_store_owner_gets_403(self):
        store = self._create_store(name="Patch Owner Forbidden", status="active")
        self._as_store_owner()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "suspended"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", response.json())

    def test_store_status_patch_missing_token_gets_401(self):
        store = self._create_store(name="Patch Missing Token", status="active")

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "suspended"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_store_status_patch_does_not_change_other_store_fields(self):
        store = self._create_store(
            name="Patch Stable Fields",
            status="setup",
            subdomain="stable-subdomain",
        )
        original = {
            "slug": store.slug,
            "subdomain": store.subdomain,
            "owner_id": store.owner_id,
            "tenant_id": store.tenant_id,
        }
        self._as_super_admin()

        response = self.client.patch(
            f"/api/admin/stores/{store.id}/status/",
            {"status": "active"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        store.refresh_from_db()
        self.assertEqual(store.slug, original["slug"])
        self.assertEqual(store.subdomain, original["subdomain"])
        self.assertEqual(store.owner_id, original["owner_id"])
        self.assertEqual(store.tenant_id, original["tenant_id"])
