from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from orders.models import Address, Customer, Order, OrderItem
from products.models import Product
from stores.models import Store
from users.models import User


class PublicCartCheckoutEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="checkout_owner",
            email="checkout_owner@example.com",
            password="StrongPass123!",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 701
        self.owner.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Checkout Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=True,
            subdomain="checkout-store",
        )
        self.unpublished_store = Store.objects.create(
            owner=self.owner,
            name="Checkout Store Draft",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=False,
            subdomain="checkout-draft",
        )
        self.inactive_store = Store.objects.create(
            owner=self.owner,
            name="Checkout Store Inactive",
            tenant_id=self.owner.tenant_id,
            status="inactive",
            is_published=True,
            subdomain="checkout-inactive",
        )

        self.product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Checkout Product",
            description="Active",
            price=Decimal("11.00"),
            sku="CHECKOUT-1",
            status="active",
        )
        self.second_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Checkout Product 2",
            description="Active",
            price=Decimal("5.50"),
            sku="CHECKOUT-2",
            status="active",
        )

    @staticmethod
    def _payload(response):
        return response.json()

    def _cart_items_url(self, subdomain):
        return f"/api/public/store/{subdomain}/cart/items/"

    def _cart_url(self, subdomain):
        return f"/api/public/store/{subdomain}/cart/"

    def _checkout_url(self, subdomain):
        return f"/api/public/store/{subdomain}/cart/checkout/"

    def _checkout_body(self, email="checkout_customer@example.com"):
        return {
            "customer": {
                "name": "Checkout Customer",
                "email": email,
                "phone": "+1-555-2000",
            },
            "address": {
                "country": "US",
                "city": "Los Angeles",
                "street": "Sunset Blvd",
                "postal_code": "90001",
            },
        }

    def _add_cart_item(self, token, product_id, quantity):
        return self.client.post(
            self._cart_items_url(self.store.subdomain),
            {"product_id": product_id, "quantity": quantity},
            format="json",
            HTTP_X_CART_TOKEN=token,
        )

    def test_successful_checkout_from_cart_returns_201_and_clears_cart(self):
        self._add_cart_item("checkout-token-1", self.product.id, 2)
        self._add_cart_item("checkout-token-1", self.second_product.id, 1)

        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-1",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = self._payload(response)
        self.assertIn("order_id", payload)
        self.assertIn("status", payload)
        self.assertIn("total", payload)
        self.assertEqual(payload["status"], "pending")

        order = Order.objects.get(id=payload["order_id"])
        expected_total = (self.product.price * 2) + self.second_product.price
        self.assertEqual(order.total_price, expected_total)
        self.assertEqual(Decimal(str(payload["total"])), expected_total)

        self.assertEqual(Customer.objects.filter(store=self.store).count(), 1)
        self.assertEqual(Address.objects.filter(customer=order.customer).count(), 1)
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)

        cart_response = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="checkout-token-1",
        )
        self.assertEqual(cart_response.status_code, status.HTTP_200_OK)
        cart_payload = self._payload(cart_response)
        self.assertEqual(cart_payload["items"], [])
        self.assertEqual(Decimal(str(cart_payload["total"])), Decimal("0.00"))

    def test_checkout_with_empty_cart_returns_400(self):
        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(),
            format="json",
            HTTP_X_CART_TOKEN="empty-cart-token",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cart is empty", response.content.decode("utf-8"))

    def test_checkout_unknown_subdomain_returns_404(self):
        response = self.client.post(
            self._checkout_url("unknown-store"),
            self._checkout_body(),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-2",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_checkout_invalid_body_returns_400(self):
        missing_customer = {
            "address": self._checkout_body()["address"],
        }
        missing_address = {
            "customer": self._checkout_body()["customer"],
        }

        self._add_cart_item("checkout-token-3", self.product.id, 1)

        for body in [missing_customer, missing_address]:
            with self.subTest(body=body):
                response = self.client.post(
                    self._checkout_url(self.store.subdomain),
                    body,
                    format="json",
                    HTTP_X_CART_TOKEN="checkout-token-3",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_with_product_became_inactive_returns_400(self):
        self._add_cart_item("checkout-token-4", self.product.id, 1)
        self.product.status = "draft"
        self.product.save(update_fields=["status"])

        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-4",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_with_product_no_longer_resolvable_returns_400(self):
        self._add_cart_item("checkout-token-5", self.product.id, 1)
        self.product.delete()

        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-5",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_reuses_existing_customer_by_email(self):
        existing_customer = Customer.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Existing Name",
            email="same@example.com",
            phone="0000",
        )
        self._add_cart_item("checkout-token-6", self.product.id, 1)

        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(email="same@example.com"),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-6",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Customer.objects.filter(store=self.store, email__iexact="same@example.com").count(),
            1,
        )

        existing_customer.refresh_from_db()
        self.assertEqual(existing_customer.name, "Checkout Customer")
        self.assertEqual(existing_customer.phone, "+1-555-2000")

        order = Order.objects.get(id=self._payload(response)["order_id"])
        self.assertEqual(order.customer_id, existing_customer.id)

    def test_checkout_isolation_by_cart_token(self):
        self._add_cart_item("checkout-token-a", self.product.id, 1)
        self._add_cart_item("checkout-token-b", self.second_product.id, 2)

        response = self.client.post(
            self._checkout_url(self.store.subdomain),
            self._checkout_body(email="token-a@example.com"),
            format="json",
            HTTP_X_CART_TOKEN="checkout-token-a",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        token_a_cart = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="checkout-token-a",
        )
        token_b_cart = self.client.get(
            self._cart_url(self.store.subdomain),
            HTTP_X_CART_TOKEN="checkout-token-b",
        )
        self.assertEqual(self._payload(token_a_cart)["items"], [])
        self.assertEqual(len(self._payload(token_b_cart)["items"]), 1)

    def test_checkout_unpublished_or_inactive_store_returns_404(self):
        for subdomain in [self.unpublished_store.subdomain, self.inactive_store.subdomain]:
            with self.subTest(subdomain=subdomain):
                response = self.client.post(
                    self._checkout_url(subdomain),
                    self._checkout_body(),
                    format="json",
                    HTTP_X_CART_TOKEN="checkout-token-store-404",
                )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
