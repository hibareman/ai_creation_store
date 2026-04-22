from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from orders.models import Address, Customer, Order, OrderItem
from products.models import Product
from stores.models import Store
from users.models import User


class PublicCreateOrderEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="public_store_owner",
            email="public_owner@example.com",
            password="StrongPass123!",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 301
        self.owner.save()

        self.public_store = Store.objects.create(
            owner=self.owner,
            name="Public Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=True,
            subdomain="public-shop",
        )
        self.unpublished_store = Store.objects.create(
            owner=self.owner,
            name="Unpublished Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=False,
            subdomain="draft-shop",
        )
        self.inactive_store = Store.objects.create(
            owner=self.owner,
            name="Inactive Store",
            tenant_id=self.owner.tenant_id,
            status="inactive",
            is_published=True,
            subdomain="inactive-shop",
        )
        self.other_store_same_tenant = Store.objects.create(
            owner=self.owner,
            name="Other Store",
            tenant_id=self.owner.tenant_id,
            status="active",
            is_published=True,
            subdomain="other-shop",
        )

        self.active_product_1 = Product.objects.create(
            store=self.public_store,
            tenant_id=self.public_store.tenant_id,
            name="Product A",
            description="Active product A",
            price=Decimal("10.00"),
            sku="PUBLIC-A",
            status="active",
        )
        self.active_product_2 = Product.objects.create(
            store=self.public_store,
            tenant_id=self.public_store.tenant_id,
            name="Product B",
            description="Active product B",
            price=Decimal("25.50"),
            sku="PUBLIC-B",
            status="active",
        )
        self.inactive_product = Product.objects.create(
            store=self.public_store,
            tenant_id=self.public_store.tenant_id,
            name="Product C",
            description="Inactive product",
            price=Decimal("15.00"),
            sku="PUBLIC-C",
            status="draft",
        )
        self.outside_store_product = Product.objects.create(
            store=self.other_store_same_tenant,
            tenant_id=self.other_store_same_tenant.tenant_id,
            name="Foreign Product",
            description="Belongs to another store",
            price=Decimal("40.00"),
            sku="OTHER-A",
            status="active",
        )

    @staticmethod
    def _payload(response):
        return response.json()

    def _endpoint(self, subdomain: str) -> str:
        return f"/api/public/store/{subdomain}/orders/"

    def _valid_request_body(self):
        return {
            "customer": {
                "name": "Alice Public",
                "email": "alice.public@example.com",
                "phone": "+1-555-1000",
            },
            "address": {
                "country": "US",
                "city": "San Francisco",
                "street": "Market Street",
                "postal_code": "94103",
            },
            "items": [
                {"product_id": self.active_product_1.id, "quantity": 2},
                {"product_id": self.active_product_2.id, "quantity": 1},
            ],
        }

    def test_successful_public_order_creation_returns_201(self):
        response = self.client.post(
            self._endpoint(self.public_store.subdomain),
            self._valid_request_body(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = self._payload(response)
        self.assertIn("order_id", payload)
        self.assertIn("status", payload)
        self.assertIn("total", payload)
        self.assertEqual(payload["status"], "pending")

        expected_total = (self.active_product_1.price * 2) + self.active_product_2.price
        self.assertEqual(Decimal(str(payload["total"])), expected_total)

        order = Order.objects.get(id=payload["order_id"])
        self.assertEqual(order.store_id, self.public_store.id)
        self.assertEqual(order.tenant_id, self.public_store.tenant_id)
        self.assertEqual(order.status, "pending")
        self.assertEqual(order.total_price, expected_total)

        self.assertEqual(Customer.objects.filter(store=self.public_store).count(), 1)
        self.assertEqual(Address.objects.filter(customer=order.customer).count(), 1)
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 2)

        first_item = OrderItem.objects.filter(order=order, product=self.active_product_1).first()
        self.assertIsNotNone(first_item)
        self.assertEqual(first_item.product_name, self.active_product_1.name)
        self.assertEqual(first_item.product_price, self.active_product_1.price)
        self.assertEqual(first_item.quantity, 2)

    def test_unknown_subdomain_returns_404(self):
        response = self.client.post(
            self._endpoint("unknown-store"),
            self._valid_request_body(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertEqual(str(payload["detail"]), "Store not found")

    def test_invalid_request_body_returns_400(self):
        invalid_payloads = [
            {
                "address": {
                    "country": "US",
                    "city": "SF",
                    "street": "A",
                    "postal_code": "1",
                },
                "items": [{"product_id": self.active_product_1.id, "quantity": 1}],
            },
            {
                "customer": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "phone": "",
                },
                "items": [{"product_id": self.active_product_1.id, "quantity": 1}],
            },
            {
                "customer": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "phone": "",
                },
                "address": {
                    "country": "US",
                    "city": "SF",
                    "street": "A",
                    "postal_code": "1",
                },
                "items": [],
            },
            {
                "customer": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "phone": "",
                },
                "address": {
                    "country": "US",
                    "city": "SF",
                    "street": "A",
                    "postal_code": "1",
                },
                "items": [{"product_id": self.active_product_1.id, "quantity": 0}],
            },
        ]

        for body in invalid_payloads:
            with self.subTest(body=body):
                response = self.client.post(
                    self._endpoint(self.public_store.subdomain),
                    body,
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_product_not_found_or_outside_store_or_inactive_returns_400(self):
        cases = [
            [{"product_id": 999999, "quantity": 1}],
            [{"product_id": self.outside_store_product.id, "quantity": 1}],
            [{"product_id": self.inactive_product.id, "quantity": 1}],
        ]

        for items in cases:
            with self.subTest(items=items):
                body = self._valid_request_body()
                body["items"] = items
                response = self.client.post(
                    self._endpoint(self.public_store.subdomain),
                    body,
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("unavailable", response.content.decode("utf-8").lower())

    def test_non_published_or_inactive_store_returns_404(self):
        for subdomain in [self.unpublished_store.subdomain, self.inactive_store.subdomain]:
            with self.subTest(subdomain=subdomain):
                response = self.client.post(
                    self._endpoint(subdomain),
                    self._valid_request_body(),
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_existing_customer_same_email_is_reused(self):
        existing_customer = Customer.objects.create(
            store=self.public_store,
            tenant_id=self.public_store.tenant_id,
            name="Old Name",
            email="repeat@example.com",
            phone="0000",
        )

        body = self._valid_request_body()
        body["customer"] = {
            "name": "New Name",
            "email": "repeat@example.com",
            "phone": "1111",
        }

        response = self.client.post(
            self._endpoint(self.public_store.subdomain),
            body,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Customer.objects.filter(
                store=self.public_store,
                email__iexact="repeat@example.com",
            ).count(),
            1,
        )

        existing_customer.refresh_from_db()
        self.assertEqual(existing_customer.name, "New Name")
        self.assertEqual(existing_customer.phone, "1111")

        order_id = self._payload(response)["order_id"]
        order = Order.objects.get(id=order_id)
        self.assertEqual(order.customer_id, existing_customer.id)
