from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from products.models import Product
from stores.models import Store
from users.models import User


class PublicCartEndpointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="cart_owner",
            email="cart_owner@example.com",
            password="StrongPass123!",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 501
        self.owner.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Cart Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=True,
            subdomain="cart-store",
        )
        self.second_store = Store.objects.create(
            owner=self.owner,
            name="Second Cart Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=True,
            subdomain="cart-store-2",
        )

        self.active_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Active Product",
            description="Active",
            price=Decimal("12.50"),
            sku="CART-ACTIVE-1",
            status="active",
        )
        self.active_product_second_store = Product.objects.create(
            store=self.second_store,
            tenant_id=self.second_store.tenant_id,
            name="Second Store Product",
            description="Active",
            price=Decimal("9.99"),
            sku="CART-ACTIVE-2",
            status="active",
        )
        self.inactive_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Inactive Product",
            description="Draft",
            price=Decimal("7.00"),
            sku="CART-INACTIVE-1",
            status="draft",
        )

    @staticmethod
    def _payload(response):
        return response.json()

    def _cart_url(self, subdomain):
        return f"/api/public/store/{subdomain}/cart/"

    def _cart_items_url(self, subdomain):
        return f"/api/public/store/{subdomain}/cart/items/"

    def _cart_item_detail_url(self, subdomain, product_id):
        return f"/api/public/store/{subdomain}/cart/items/{product_id}/"

    def test_view_empty_cart_returns_200(self):
        response = self.client.get(self._cart_url(self.store.subdomain))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = self._payload(response)
        self.assertIn("cart_token", payload)
        self.assertEqual(payload["store_id"], self.store.id)
        self.assertEqual(payload["items"], [])
        self.assertEqual(Decimal(str(payload["total"])), Decimal("0.00"))
        self.assertTrue(response["X-Cart-Token"])

    def test_add_active_product_to_cart(self):
        response = self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 2},
            format="json",
            HTTP_X_CART_TOKEN="cart-add-1",
        )
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_201_CREATED])

        payload = self._payload(response)
        self.assertEqual(payload["store_id"], self.store.id)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["product_id"], self.active_product.id)
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(Decimal(str(item["line_total"])), self.active_product.price * 2)
        self.assertEqual(Decimal(str(payload["total"])), self.active_product.price * 2)

    def test_add_same_product_merges_quantity(self):
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 1},
            format="json",
            HTTP_X_CART_TOKEN="cart-merge-1",
        )
        response = self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 3},
            format="json",
            HTTP_X_CART_TOKEN="cart-merge-1",
        )

        payload = self._payload(response)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["quantity"], 4)

    def test_update_item_quantity(self):
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 1},
            format="json",
            HTTP_X_CART_TOKEN="cart-update-1",
        )

        response = self.client.patch(
            self._cart_item_detail_url(self.store.subdomain, self.active_product.id),
            {"quantity": 5},
            format="json",
            HTTP_X_CART_TOKEN="cart-update-1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payload = self._payload(response)
        self.assertEqual(payload["items"][0]["quantity"], 5)
        self.assertEqual(Decimal(str(payload["items"][0]["line_total"])), self.active_product.price * 5)
        self.assertEqual(Decimal(str(payload["total"])), self.active_product.price * 5)

    def test_remove_item(self):
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 2},
            format="json",
            HTTP_X_CART_TOKEN="cart-remove-1",
        )

        response = self.client.delete(
            self._cart_item_detail_url(self.store.subdomain, self.active_product.id),
            HTTP_X_CART_TOKEN="cart-remove-1",
        )
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])

        verify = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="cart-remove-1",
        )
        payload = self._payload(verify)
        self.assertEqual(payload["items"], [])
        self.assertEqual(Decimal(str(payload["total"])), Decimal("0.00"))

    def test_clear_cart(self):
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 2},
            format="json",
            HTTP_X_CART_TOKEN="cart-clear-1",
        )

        response = self.client.delete(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="cart-clear-1",
        )
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT])

        verify = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="cart-clear-1",
        )
        payload = self._payload(verify)
        self.assertEqual(payload["items"], [])
        self.assertEqual(Decimal(str(payload["total"])), Decimal("0.00"))

    def test_invalid_quantity_returns_400(self):
        add_response = self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 0},
            format="json",
            HTTP_X_CART_TOKEN="cart-invalid-q",
        )
        self.assertEqual(add_response.status_code, status.HTTP_400_BAD_REQUEST)

        patch_response = self.client.patch(
            self._cart_item_detail_url(self.store.subdomain, self.active_product.id),
            {"quantity": 0},
            format="json",
            HTTP_X_CART_TOKEN="cart-invalid-q",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_missing_or_outside_store_product_returns_400(self):
        for product_id in [999999, self.inactive_product.id, self.active_product_second_store.id]:
            with self.subTest(product_id=product_id):
                response = self.client.post(
                    self._cart_items_url(self.store.subdomain),
                    {"product_id": product_id, "quantity": 1},
                    format="json",
                    HTTP_X_CART_TOKEN="cart-product-invalid",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_subdomain_returns_404(self):
        response = self.client.get(self._cart_url("unknown-store"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cart_isolation_by_cart_token(self):
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 2},
            format="json",
            HTTP_X_CART_TOKEN="token-a",
        )
        token_a_response = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="token-a",
        )
        token_b_response = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="token-b",
        )

        self.assertEqual(len(self._payload(token_a_response)["items"]), 1)
        self.assertEqual(self._payload(token_b_response)["items"], [])

    def test_cart_isolation_by_store(self):
        shared_token = "shared-token"
        self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": self.active_product.id, "quantity": 1},
            format="json",
            HTTP_X_CART_TOKEN=shared_token,
        )

        store_one_cart = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN=shared_token,
        )
        store_two_cart = self.client.get(
            self._cart_url(self.second_store.subdomain),
            HTTP_X_CART_TOKEN=shared_token,
        )

        self.assertEqual(len(self._payload(store_one_cart)["items"]), 1)
        self.assertEqual(self._payload(store_two_cart)["items"], [])
