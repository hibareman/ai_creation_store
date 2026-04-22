from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from orders.models import Address, Customer, Order, OrderItem
from stores.models import Store
from users.models import User


class OwnerEndpointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = self._create_user(
            username="owner",
            email="owner@example.com",
            tenant_id=101,
        )
        self.same_tenant_non_owner = self._create_user(
            username="same_tenant_non_owner",
            email="same_tenant_non_owner@example.com",
            tenant_id=101,
        )
        self.other_tenant_user = self._create_user(
            username="other_tenant_user",
            email="other_tenant_user@example.com",
            tenant_id=202,
        )

        self.owner_store = Store.objects.create(
            owner=self.owner,
            name="Owner Store",
            tenant_id=self.owner.tenant_id,
            status="active",
        )
        self.other_tenant_store = Store.objects.create(
            owner=self.other_tenant_user,
            name="Other Tenant Store",
            tenant_id=self.other_tenant_user.tenant_id,
            status="active",
        )

        self.customer = Customer.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            name="Alice Buyer",
            email="alice@example.com",
            phone="+1-555-0100",
            avatar_url="https://example.com/avatar.png",
        )
        Address.objects.create(
            customer=self.customer,
            country="US",
            city="San Francisco",
            street="Market Street",
            postal_code="94103",
        )
        self.owner_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status="pending",
            total_price=Decimal("120.00"),
        )
        OrderItem.objects.create(
            order=self.owner_order,
            product=None,
            product_name="Starter Package",
            product_price=Decimal("40.00"),
            quantity=3,
        )

        other_customer = Customer.objects.create(
            store=self.other_tenant_store,
            tenant_id=self.other_tenant_store.tenant_id,
            name="Bob Foreign",
            email="bob@example.com",
            phone="+1-555-0200",
            avatar_url="",
        )
        self.other_tenant_order = Order.objects.create(
            store=self.other_tenant_store,
            customer=other_customer,
            tenant_id=self.other_tenant_store.tenant_id,
            status="pending",
            total_price=Decimal("75.00"),
        )

        self.owner_auth = self._auth(self.owner)
        self.same_tenant_auth = self._auth(self.same_tenant_non_owner)
        self.other_tenant_auth = self._auth(self.other_tenant_user)

    @staticmethod
    def _create_user(*, username: str, email: str, tenant_id: int) -> User:
        user = User.objects.create_user(
            username=username,
            email=email,
            password="StrongPass123!",
        )
        user.is_active = True
        user.tenant_id = tenant_id
        user.save()
        return user

    @staticmethod
    def _auth(user: User) -> str:
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    @staticmethod
    def _payload(response):
        return response.json()

    def test_dashboard_owner_can_access(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["store_id"], self.owner_store.id)
        self.assertIn("stats", payload)
        self.assertIn("recent_orders", payload)
        self.assertIn("top_products", payload)

    def test_dashboard_unauthenticated_returns_401(self):
        response = self.client.get(f"/api/stores/{self.owner_store.id}/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_dashboard_same_tenant_non_owner_returns_403(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_cross_tenant_store_returns_404(self):
        response = self.client.get(
            f"/api/stores/{self.other_tenant_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customers_owner_can_access(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/customers/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["store_id"], self.owner_store.id)
        self.assertIn("items", payload)
        self.assertTrue(len(payload["items"]) >= 1)

        item = payload["items"][0]
        expected_fields = {
            "id",
            "store_id",
            "name",
            "email",
            "phone",
            "total_spent",
            "last_order_at",
            "avatar_url",
            "orders_count",
        }
        self.assertTrue(expected_fields.issubset(set(item.keys())))

    def test_customers_unauthenticated_returns_401(self):
        response = self.client.get(f"/api/stores/{self.owner_store.id}/customers/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_customers_same_tenant_non_owner_returns_403(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/customers/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customers_cross_tenant_store_returns_404(self):
        response = self.client.get(
            f"/api/stores/{self.other_tenant_store.id}/customers/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_orders_owner_can_access(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["store_id"], self.owner_store.id)
        self.assertIn("items", payload)
        self.assertTrue(len(payload["items"]) >= 1)

        order_item = payload["items"][0]
        expected_order_fields = {
            "id",
            "store_id",
            "customer_id",
            "customer_name",
            "email",
            "phone",
            "address",
            "total",
            "status",
            "created_at",
            "items",
        }
        self.assertTrue(expected_order_fields.issubset(set(order_item.keys())))
        self.assertTrue(len(order_item["items"]) >= 1)

        nested_item = order_item["items"][0]
        expected_nested_fields = {"id", "name", "quantity", "price"}
        self.assertTrue(expected_nested_fields.issubset(set(nested_item.keys())))

    def test_orders_unauthenticated_returns_401(self):
        response = self.client.get(f"/api/stores/{self.owner_store.id}/orders/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_orders_same_tenant_non_owner_returns_403(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_orders_cross_tenant_store_returns_404(self):
        response = self.client.get(
            f"/api/stores/{self.other_tenant_store.id}/orders/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_order_detail_owner_can_access(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("order", payload)
        self.assertEqual(payload["order"]["id"], self.owner_order.id)
        self.assertEqual(payload["order"]["store_id"], self.owner_store.id)

    def test_order_detail_unauthenticated_returns_401(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_order_detail_same_tenant_non_owner_returns_403(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_order_detail_cross_tenant_store_returns_404(self):
        response = self.client.get(
            f"/api/stores/{self.other_tenant_store.id}/orders/{self.other_tenant_order.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_order_detail_missing_order_returns_404(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/999999/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_order_status_owner_success(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/status/",
            {"status": "shipped"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("order", payload)
        self.assertEqual(payload["order"]["id"], self.owner_order.id)
        self.assertEqual(payload["order"]["status"], "shipped")

        self.owner_order.refresh_from_db()
        self.assertEqual(self.owner_order.status, "shipped")

    def test_update_order_status_invalid_value_returns_400(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/status/",
            {"status": "confirmed"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_order_status_unauthenticated_returns_401(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/status/",
            {"status": "shipped"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_order_status_same_tenant_non_owner_returns_403(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/status/",
            {"status": "shipped"},
            format="json",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_order_status_cross_tenant_store_returns_404(self):
        response = self.client.patch(
            f"/api/stores/{self.other_tenant_store.id}/orders/{self.other_tenant_order.id}/status/",
            {"status": "shipped"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_order_status_cross_tenant_order_returns_404(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.other_tenant_order.id}/status/",
            {"status": "shipped"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_order_status_missing_order_returns_404(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/999999/status/",
            {"status": "shipped"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
