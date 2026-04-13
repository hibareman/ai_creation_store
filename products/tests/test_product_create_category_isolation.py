from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from categories.models import Category
from products.models import Inventory, Product
from stores.models import Store
from users.models import User


class ProductCreateCategoryIsolationTests(TestCase):

    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create(
            username="owner",
            email="owner@example.com",
            role="Store Owner",
            is_active=True,
        )
        self.user.set_password("StrongPass123!")
        self.user.save()
        self.user.tenant_id = self.user.id
        self.user.save(update_fields=["tenant_id"])

        self.store_a = Store.objects.create(owner=self.user, name="Store A")
        self.store_b = Store.objects.create(owner=self.user, name="Store B")

        self.category_a = Category.objects.create(
            store=self.store_a,
            name="Category A",
            description="Category for store A",
        )
        self.category_b = Category.objects.create(
            store=self.store_b,
            name="Category B",
            description="Category for store B",
        )

        refresh = RefreshToken.for_user(self.user)
        self.auth_header = f"Bearer {str(refresh.access_token)}"

    def test_create_product_rejects_category_from_another_store(self):
        payload = {
            "name": "Cross Store Product",
            "description": "Should fail",
            "price": "19.99",
            "sku": "CROSS-001",
            "status": "active",
            "category": self.category_b.id,
        }

        response = self.client.post(
            f"/api/products/{self.store_a.id}/products/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Category does not belong to this store",
            str(response.data.get("detail", "")),
        )
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(Inventory.objects.count(), 0)

    def test_create_product_with_same_store_category_succeeds(self):
        payload = {
            "name": "Valid Product",
            "description": "Should succeed",
            "price": "29.99",
            "sku": "VALID-001",
            "status": "active",
            "category": self.category_a.id,
        }

        response = self.client.post(
            f"/api/products/{self.store_a.id}/products/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )

        self.assertEqual(response.status_code, 201)
        product = Product.objects.get(store=self.store_a, sku="VALID-001")
        self.assertEqual(product.category_id, self.category_a.id)
        self.assertTrue(Inventory.objects.filter(product=product).exists())
