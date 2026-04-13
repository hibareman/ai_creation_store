from django.test import TestCase
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store
from users.models import User


class ProductStoreOwnershipAuthorizationTests(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user_a = User.objects.create(
            username="owner_a",
            email="owner_a@example.com",
            role="Store Owner",
            is_active=True,
        )
        self.user_a.set_password("StrongPass123!")
        self.user_a.save()
        self.user_a.tenant_id = 500
        self.user_a.save(update_fields=["tenant_id"])

        self.user_b = User.objects.create(
            username="owner_b",
            email="owner_b@example.com",
            role="Store Owner",
            is_active=True,
            tenant_id=500,
        )
        self.user_b.set_password("StrongPass123!")
        self.user_b.save()

        self.store = Store.objects.create(owner=self.user_a, name="Owner A Store")
        self.category = Category.objects.create(
            store=self.store,
            name="Store Category",
            description="Owned by user_a store",
        )
        self.product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Owner Product",
            description="Initial",
            price=Decimal("99.99"),
            sku="OWNER-001",
            category=self.category,
            status="active",
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            stock_quantity=10,
        )
        self.image = ProductImage.objects.create(
            product=self.product,
            image_url="https://example.com/initial.jpg",
        )

        refresh = RefreshToken.for_user(self.user_b)
        self.auth_header = f"Bearer {str(refresh.access_token)}"

    def test_non_owner_same_tenant_cannot_list_products(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)

    def test_non_owner_same_tenant_cannot_create_product(self):
        payload = {
            "name": "Hacker Product",
            "description": "Should be denied",
            "price": "15.00",
            "sku": "HACKER-001",
            "status": "active",
            "category": self.category.id,
        }
        response = self.client.post(
            f"/api/products/{self.store.id}/products/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.filter(sku="HACKER-001").exists())

    def test_non_owner_same_tenant_cannot_retrieve_product(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)

    def test_non_owner_same_tenant_cannot_update_product(self):
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {"name": "Compromised Name"},
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Owner Product")

    def test_non_owner_same_tenant_cannot_delete_product(self):
        response = self.client.delete(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

    def test_non_owner_same_tenant_cannot_update_inventory(self):
        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/inventory/",
            {"stock_quantity": 999},
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.stock_quantity, 10)

    def test_non_owner_same_tenant_cannot_add_image(self):
        response = self.client.post(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/",
            {"image_url": "https://example.com/new-image.jpg"},
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ProductImage.objects.filter(product=self.product).count(), 1)

    def test_non_owner_same_tenant_cannot_delete_image(self):
        response = self.client.delete(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/{self.image.id}/",
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ProductImage.objects.filter(id=self.image.id).exists())
