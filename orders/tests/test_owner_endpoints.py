from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from categories.models import Category
from orders.models import Address, Customer, Order, OrderItem
from products.models import Product
from stores.models import Store, StoreSettings
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

    @staticmethod
    def _order_ids(payload):
        return {item["id"] for item in payload["items"]}

    def test_dashboard_owner_can_access(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["store_id"], self.owner_store.id)
        self.assertIn("stats", payload)
        self.assertIn("financial_summary", payload)
        self.assertIn("readiness", payload)
        self.assertIn("recommended_actions", payload)
        self.assertIn("alerts", payload)
        self.assertIn("notices", payload)
        self.assertIn("recent_orders", payload)
        self.assertIn("top_products", payload)

        self.assertEqual(payload["stats"]["total_products"], 0)
        self.assertEqual(payload["stats"]["total_categories"], 0)
        self.assertEqual(payload["stats"]["total_orders"], 1)
        self.assertEqual(payload["stats"]["pending_orders"], 1)
        self.assertEqual(payload["stats"]["delivered_orders"], 0)
        self.assertEqual(Decimal(str(payload["financial_summary"]["total_sales"])), Decimal("0.00"))
        self.assertEqual(Decimal(str(payload["financial_summary"]["platform_commission"])), Decimal("0.00"))
        self.assertEqual(Decimal(str(payload["financial_summary"]["store_net_profit"])), Decimal("0.00"))
        self.assertEqual(payload["financial_summary"]["completed_orders_count"], 0)
        self.assertEqual(payload["financial_summary"]["currency"], "USD")
        self.assertEqual(payload["readiness"]["status"], "incomplete")
        self.assertFalse(payload["readiness"]["is_ready_for_publish"])
        self.assertEqual(payload["readiness"]["completion_percentage"], 0)
        self.assertEqual(
            set(payload["readiness"]["missing_requirements"]),
            {"categories", "products", "subdomain", "publishing"},
        )
        self.assertEqual(
            {item["code"] for item in payload["recommended_actions"]},
            {"add_category", "add_product", "set_subdomain"},
        )
        self.assertEqual(payload["alerts"][0]["code"], "orders_need_review")
        self.assertEqual(payload["alerts"][0]["count"], 1)
        self.assertIn("need review and processing", payload["alerts"][0]["message"])
        action_messages = {item["code"]: item["message"] for item in payload["recommended_actions"]}
        self.assertIn("no categories yet", action_messages["add_category"])
        self.assertIn("no products yet", action_messages["add_product"])
        self.assertIn("does not have a public link yet", action_messages["set_subdomain"])

    def test_dashboard_stale_pending_order_returns_english_warning(self):
        stale_created_at = timezone.now() - timedelta(days=4)
        Order.objects.filter(id=self.owner_order.id).update(created_at=stale_created_at)

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        alerts = {item["code"]: item for item in self._payload(response)["alerts"]}
        self.assertIn("stale_pending_orders", alerts)
        self.assertIn("pending for more than 3 days", alerts["stale_pending_orders"]["message"])
        self.assertEqual(alerts["stale_pending_orders"]["severity"], "warning")

    def test_dashboard_financials_use_delivered_orders_only(self):
        StoreSettings.objects.create(store=self.owner_store, currency="SYP")
        delivered_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status=Order.STATUS_DELIVERED,
            total_price=Decimal("200.00"),
        )
        Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status=Order.STATUS_PROCESSING,
            total_price=Decimal("500.00"),
        )
        foreign_delivered = Order.objects.create(
            store=self.other_tenant_store,
            customer=self.other_tenant_order.customer,
            tenant_id=self.other_tenant_store.tenant_id,
            status=Order.STATUS_DELIVERED,
            total_price=Decimal("999.00"),
        )

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        financial = payload["financial_summary"]
        self.assertEqual(financial["completed_orders_count"], 1)
        self.assertEqual(Decimal(str(financial["total_sales"])), Decimal("200.00"))
        self.assertEqual(Decimal(str(financial["commission_rate_percent"])), Decimal("10.00"))
        self.assertEqual(Decimal(str(financial["platform_commission"])), Decimal("20.00"))
        self.assertEqual(Decimal(str(financial["store_net_profit"])), Decimal("180.00"))
        self.assertEqual(financial["currency"], "SYP")
        self.assertEqual(Decimal(str(payload["stats"]["total_revenue"])), Decimal("200.00"))
        self.assertEqual(payload["stats"]["delivered_orders"], 1)
        self.assertNotEqual(delivered_order.store_id, foreign_delivered.store_id)

    def test_dashboard_readiness_ready_to_publish(self):
        category = Category.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            name="Electronics",
        )
        Product.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            category=category,
            name="Smart Device",
            description="Example product",
            price=Decimal("50.00"),
            sku="SMART-001",
            status="active",
        )
        self.owner_store.subdomain = "owner-store"
        self.owner_store.save(update_fields=["subdomain"])

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["readiness"]["status"], "ready_to_publish")
        self.assertTrue(payload["readiness"]["is_ready_for_publish"])
        self.assertEqual(payload["readiness"]["completion_percentage"], 75)
        self.assertEqual(payload["readiness"]["missing_requirements"], ["publishing"])
        self.assertEqual(
            {item["code"] for item in payload["recommended_actions"]},
            {"add_more_products", "publish_store"},
        )
        publish_action = next(
            item for item in payload["recommended_actions"]
            if item["code"] == "publish_store"
        )
        self.assertIn("ready", publish_action["message"])

    def test_dashboard_readiness_published_store(self):
        category = Category.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            name="Published Category",
        )
        Product.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            category=category,
            name="Published Product",
            description="Example product",
            price=Decimal("75.00"),
            sku="PUBLISHED-001",
            status="active",
        )
        self.owner_store.subdomain = "published-store"
        self.owner_store.is_published = True
        self.owner_store.status = "active"
        self.owner_store.save(update_fields=["subdomain", "is_published", "status"])

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["readiness"]["status"], "published")
        self.assertTrue(payload["readiness"]["is_ready_for_publish"])
        self.assertEqual(payload["readiness"]["completion_percentage"], 100)
        self.assertEqual(payload["readiness"]["missing_requirements"], [])
        self.assertEqual(
            {item["code"] for item in payload["recommended_actions"]},
            {"add_more_products", "improve_sales"},
        )
        self.assertEqual(payload["notices"], [])

    def test_dashboard_low_product_guidance_uses_english_message(self):
        category = Category.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            name="Small Catalog",
        )
        Product.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            category=category,
            name="Single Product",
            description="Example product",
            price=Decimal("25.00"),
            sku="SINGLE-001",
            status="active",
        )

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actions = {item["code"]: item for item in self._payload(response)["recommended_actions"]}
        self.assertIn("add_more_products", actions)
        self.assertIn("currently has only 1 product", actions["add_more_products"]["message"])

    def test_dashboard_healthy_published_store_returns_success_notice(self):
        category = Category.objects.create(
            store=self.owner_store,
            tenant_id=self.owner_store.tenant_id,
            name="Healthy Catalog",
        )
        for index in range(5):
            Product.objects.create(
                store=self.owner_store,
                tenant_id=self.owner_store.tenant_id,
                category=category,
                name=f"Healthy Product {index}",
                description="Example product",
                price=Decimal("25.00"),
                sku=f"HEALTHY-{index}",
                status="active",
            )
        self.owner_store.subdomain = "healthy-store"
        self.owner_store.is_published = True
        self.owner_store.status = "active"
        self.owner_store.save(update_fields=["subdomain", "is_published", "status"])
        self.owner_order.status = Order.STATUS_DELIVERED
        self.owner_order.save(update_fields=["status"])

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["recommended_actions"], [])
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["notices"][0]["code"], "store_running_well")
        self.assertIn("No actions are required", payload["notices"][0]["message"])


    def test_dashboard_empty_store_returns_zero_values_and_guidance(self):
        empty_store = Store.objects.create(
            owner=self.owner,
            name="Empty Dashboard Store",
            tenant_id=self.owner.tenant_id,
            status="setup",
        )

        response = self.client.get(
            f"/api/stores/{empty_store.id}/dashboard/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["stats"]["total_orders"], 0)
        self.assertEqual(payload["stats"]["total_products"], 0)
        self.assertEqual(payload["stats"]["total_categories"], 0)
        self.assertEqual(Decimal(str(payload["financial_summary"]["total_sales"])), Decimal("0.00"))
        self.assertEqual(payload["alerts"], [])
        self.assertEqual(payload["readiness"]["status"], "incomplete")
        self.assertEqual(
            {item["code"] for item in payload["recommended_actions"]},
            {"add_category", "add_product", "set_subdomain"},
        )

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
            "financial_summary",
        }
        self.assertTrue(expected_order_fields.issubset(set(order_item.keys())))
        self.assertTrue(len(order_item["items"]) >= 1)
        self.assertFalse(order_item["financial_summary"]["commission_applied"])
        self.assertEqual(
            Decimal(str(order_item["financial_summary"]["platform_commission"])),
            Decimal("0.00"),
        )

        nested_item = order_item["items"][0]
        expected_nested_fields = {"id", "name", "quantity", "price"}
        self.assertTrue(expected_nested_fields.issubset(set(nested_item.keys())))

    def test_orders_filtering_by_every_supported_status(self):
        status_to_order = {
            "pending": self.owner_order,
        }
        for status_value in ["processing", "shipped", "delivered", "cancelled"]:
            status_to_order[status_value] = Order.objects.create(
                store=self.owner_store,
                customer=self.customer,
                tenant_id=self.owner_store.tenant_id,
                status=status_value,
                total_price=Decimal("45.00"),
            )

        for status_value, order in status_to_order.items():
            response = self.client.get(
                f"/api/stores/{self.owner_store.id}/orders/?status={status_value}",
                HTTP_AUTHORIZATION=self.owner_auth,
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            payload = self._payload(response)
            self.assertEqual(payload["store_id"], self.owner_store.id)
            self.assertEqual(self._order_ids(payload), {order.id})

    def test_orders_filtering_unsupported_status_returns_400(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?status=completed",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", self._payload(response))

    def test_order_filters_keep_tenant_and_store_isolation(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?status=pending",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(self._order_ids(payload), {self.owner_order.id})
        self.assertNotIn(self.other_tenant_order.id, self._order_ids(payload))

    def test_orders_list_empty_store_data(self):
        empty_store = Store.objects.create(
            owner=self.owner,
            name="Empty Orders Store",
            tenant_id=self.owner.tenant_id,
            status="active",
        )

        response = self.client.get(
            f"/api/stores/{empty_store.id}/orders/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(payload["store_id"], empty_store.id)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["financial_summary"]["completed_orders_count"], 0)
        self.assertEqual(
            Decimal(str(payload["financial_summary"]["platform_commission"])),
            Decimal("0.00"),
        )

    def test_orders_reset_filters_returns_complete_store_scoped_list(self):
        processing_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status="processing",
            total_price=Decimal("55.00"),
        )

        filtered = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?status=processing",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        reset = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(reset.status_code, status.HTTP_200_OK)
        self.assertEqual(self._order_ids(self._payload(filtered)), {processing_order.id})
        self.assertEqual(self._order_ids(self._payload(reset)), {self.owner_order.id, processing_order.id})
        self.assertIn("items", self._payload(reset))

    def test_orders_search_by_order_number(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?search=ORD-{self.owner_order.id}",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._order_ids(self._payload(response)), {self.owner_order.id})

    def test_orders_search_by_customer_name_and_email(self):
        for search_value in ["alice", "alice@example.com"]:
            response = self.client.get(
                f"/api/stores/{self.owner_store.id}/orders/?search={search_value}",
                HTTP_AUTHORIZATION=self.owner_auth,
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self._order_ids(self._payload(response)), {self.owner_order.id})

    def test_orders_search_with_no_results_returns_empty_items(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?search=not-found",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response)["items"], [])

    def test_orders_ordering_by_total_price(self):
        cheaper_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status="processing",
            total_price=Decimal("25.00"),
        )

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?ordering=total_price",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in self._payload(response)["items"]],
            [cheaper_order.id, self.owner_order.id],
        )

    def test_orders_unsupported_ordering_returns_400(self):
        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?ordering=customer_name",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ordering", self._payload(response))

    def test_orders_combine_search_status_and_ordering(self):
        second_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status="processing",
            total_price=Decimal("15.00"),
        )

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/"
            "?search=alice&status=processing&ordering=total_price",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._order_ids(self._payload(response)), {second_order.id})

    def test_orders_financial_report_counts_only_delivered_orders(self):
        delivered_order = Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status=Order.STATUS_DELIVERED,
            total_price=Decimal("200.00"),
        )
        Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status=Order.STATUS_PROCESSING,
            total_price=Decimal("900.00"),
        )
        self.other_tenant_order.status = Order.STATUS_DELIVERED
        self.other_tenant_order.total_price = Decimal("9999.00")
        self.other_tenant_order.save(update_fields=["status", "total_price"])

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        report = payload["financial_summary"]
        self.assertEqual(report["completed_orders_count"], 1)
        self.assertEqual(Decimal(str(report["total_sales"])), Decimal("200.00"))
        self.assertEqual(Decimal(str(report["commission_rate_percent"])), Decimal("10.00"))
        self.assertEqual(Decimal(str(report["platform_commission"])), Decimal("20.00"))
        self.assertEqual(Decimal(str(report["store_net_profit"])), Decimal("180.00"))

        delivered_item = next(item for item in payload["items"] if item["id"] == delivered_order.id)
        self.assertTrue(delivered_item["financial_summary"]["commission_applied"])
        self.assertEqual(
            Decimal(str(delivered_item["financial_summary"]["platform_commission"])),
            Decimal("20.00"),
        )

    def test_orders_financial_report_respects_current_filters(self):
        Order.objects.create(
            store=self.owner_store,
            customer=self.customer,
            tenant_id=self.owner_store.tenant_id,
            status=Order.STATUS_DELIVERED,
            total_price=Decimal("200.00"),
        )

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/?status=pending",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        report = self._payload(response)["financial_summary"]
        self.assertEqual(report["completed_orders_count"], 0)
        self.assertEqual(Decimal(str(report["total_sales"])), Decimal("0.00"))
        self.assertEqual(Decimal(str(report["platform_commission"])), Decimal("0.00"))

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
        self.assertIn("financial_summary", payload)
        self.assertFalse(payload["financial_summary"]["commission_applied"])
        self.assertEqual(
            Decimal(str(payload["financial_summary"]["store_net_profit"])),
            Decimal("0.00"),
        )

        order = payload["order"]
        self.assertEqual(order["id"], self.owner_order.id)
        self.assertEqual(order["store_id"], self.owner_store.id)
        self.assertEqual(order["order_number"], f"ORD-{self.owner_order.id}")

        expected_fields = {
            "id",
            "store_id",
            "order_number",
            "status",
            "created_at",
            "updated_at",
            "subtotal",
            "shipping_fee",
            "discount",
            "total",
            "payment_method",
            "notes",
            "customer",
            "shipping_address",
            "items",
        }
        self.assertEqual(set(order.keys()), expected_fields)

        self.assertIsInstance(order["subtotal"], (int, float))
        self.assertIsInstance(order["shipping_fee"], (int, float))
        self.assertIsInstance(order["discount"], (int, float))
        self.assertIsInstance(order["total"], (int, float))

        self.assertEqual(order["customer"]["id"], self.customer.id)
        self.assertEqual(order["customer"]["name"], self.customer.name)
        self.assertEqual(order["customer"]["email"], self.customer.email)
        self.assertEqual(order["customer"]["phone"], self.customer.phone)

        self.assertEqual(order["shipping_address"]["country"], "US")
        self.assertEqual(order["shipping_address"]["city"], "San Francisco")
        self.assertEqual(order["shipping_address"]["address_line_1"], "Market Street")
        self.assertEqual(order["shipping_address"]["address_line_2"], "")
        self.assertEqual(order["shipping_address"]["postal_code"], "94103")

        self.assertEqual(len(order["items"]), 1)
        item = order["items"][0]
        expected_item_fields = {
            "id",
            "product_id",
            "product_name",
            "sku",
            "image_url",
            "quantity",
            "unit_price",
            "line_total",
        }
        self.assertEqual(set(item.keys()), expected_item_fields)
        self.assertEqual(item["product_name"], "Starter Package")
        self.assertEqual(item["quantity"], 3)
        self.assertIsInstance(item["unit_price"], (int, float))
        self.assertIsInstance(item["line_total"], (int, float))

    def test_delivered_order_detail_applies_commission(self):
        self.owner_order.status = Order.STATUS_DELIVERED
        self.owner_order.save(update_fields=["status"])

        response = self.client.get(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        financial = self._payload(response)["financial_summary"]
        self.assertTrue(financial["commission_applied"])
        self.assertEqual(Decimal(str(financial["order_total"])), Decimal("120.00"))
        self.assertEqual(Decimal(str(financial["recognized_sales"])), Decimal("120.00"))
        self.assertEqual(Decimal(str(financial["platform_commission"])), Decimal("12.00"))
        self.assertEqual(Decimal(str(financial["store_net_profit"])), Decimal("108.00"))

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

    def test_update_order_status_to_delivered_returns_commission_breakdown(self):
        response = self.client.patch(
            f"/api/stores/{self.owner_store.id}/orders/{self.owner_order.id}/status/",
            {"status": Order.STATUS_DELIVERED},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        financial = self._payload(response)["order"]["financial_summary"]
        self.assertTrue(financial["commission_applied"])
        self.assertEqual(Decimal(str(financial["platform_commission"])), Decimal("12.00"))
        self.assertEqual(Decimal(str(financial["store_net_profit"])), Decimal("108.00"))

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
