from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from stores.models import Store
from categories.models import Category
from products.models import Product


class CategoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="pass123",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 1
        self.owner.save()

        self.same_tenant_non_owner = User.objects.create_user(
            username="same_tenant_user",
            email="same_tenant@example.com",
            password="pass123",
        )
        self.same_tenant_non_owner.is_active = True
        self.same_tenant_non_owner.tenant_id = 1
        self.same_tenant_non_owner.save()

        self.other_tenant_user = User.objects.create_user(
            username="other_tenant_user",
            email="other_tenant@example.com",
            password="pass123",
        )
        self.other_tenant_user.is_active = True
        self.other_tenant_user.tenant_id = 2
        self.other_tenant_user.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Store A",
            tenant_id=1,
        )
        self.other_store = Store.objects.create(
            owner=self.other_tenant_user,
            name="Store B",
            tenant_id=2,
        )

        self.category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
            description="Electronic devices",
        )
        self.other_category = Category.objects.create(
            store=self.other_store,
            tenant_id=self.other_store.tenant_id,
            name="Books",
            description="Book products",
        )

        self.owner_auth = self._auth(self.owner)
        self.same_tenant_auth = self._auth(self.same_tenant_non_owner)
        self.other_tenant_auth = self._auth(self.other_tenant_user)

    def _auth(self, user):
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    @staticmethod
    def _payload(response):
        return response.json()

    def _assert_category_shape(self, item, *, store_id, name, description):
        self.assertIn("id", item)
        self.assertEqual(item["store_id"], store_id)
        self.assertEqual(item["name"], name)
        self.assertEqual(item["description"], description)
        self.assertIn("image_url", item)
        self.assertIn("product_count", item)
        self.assertIn("created_at", item)
        self.assertIn("updated_at", item)

    def test_list_categories_returns_current_shape(self):
        response = self.client.get(
            f"/api/categories/stores/{self.store.id}/categories/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(len(payload), 1)
        self._assert_category_shape(
            payload[0],
            store_id=self.store.id,
            name="Electronics",
            description="Electronic devices",
        )
        self.assertEqual(payload[0]["image_url"], None)
        self.assertEqual(payload[0]["product_count"], 0)

    def test_create_category_returns_current_shape(self):
        response = self.client.post(
            f"/api/categories/stores/{self.store.id}/categories/",
            {
                "name": "Clothing",
                "description": "Apparel and fashion",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = self._payload(response)
        self._assert_category_shape(
            payload,
            store_id=self.store.id,
            name="Clothing",
            description="Apparel and fashion",
        )
        self.assertEqual(payload["image_url"], None)
        self.assertEqual(payload["product_count"], 0)
        self.assertTrue(Category.objects.filter(store=self.store, name="Clothing").exists())

    def test_retrieve_category_returns_current_shape(self):
        response = self.client.get(
            f"/api/categories/stores/{self.store.id}/categories/{self.category.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_category_shape(
            payload,
            store_id=self.store.id,
            name="Electronics",
            description="Electronic devices",
        )

    def test_patch_category_returns_current_shape(self):
        response = self.client.patch(
            f"/api/categories/stores/{self.store.id}/categories/{self.category.id}/",
            {
                "name": "Consumer Electronics",
                "description": "Updated description",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_category_shape(
            payload,
            store_id=self.store.id,
            name="Consumer Electronics",
            description="Updated description",
        )
        self.assertEqual(payload["product_count"], 0)

    def test_put_category_returns_current_shape(self):
        response = self.client.put(
            f"/api/categories/stores/{self.store.id}/categories/{self.category.id}/",
            {
                "name": "Home Appliances",
                "description": "Appliances for the home",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_category_shape(
            payload,
            store_id=self.store.id,
            name="Home Appliances",
            description="Appliances for the home",
        )
        self.assertEqual(payload["product_count"], 0)

    def test_create_duplicate_category_returns_current_error_shape(self):
        response = self.client.post(
            f"/api/categories/stores/{self.store.id}/categories/",
            {
                "name": "Electronics",
                "description": "Duplicate name test",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("name", payload)
        self.assertTrue(any("already exists" in msg.lower() for msg in payload["name"]))

    def test_delete_category_success(self):
        response = self.client.delete(
            f"/api/categories/stores/{self.store.id}/categories/{self.category.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Category.objects.filter(id=self.category.id).exists())

    def test_delete_category_with_linked_products_returns_current_error_shape(self):
        Product.objects.create(
            store=self.store,
            category=self.category,
            name="Headphones",
            description="Wireless headphones",
            price=149.99,
            sku="HEADPHONES-001",
            tenant_id=self.store.tenant_id,
        )

        response = self.client.delete(
            f"/api/categories/stores/{self.store.id}/categories/{self.category.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("error", payload)
        self.assertIn("cannot delete category with assigned products", payload["error"].lower())
        self.assertTrue(Category.objects.filter(id=self.category.id).exists())

    def test_same_tenant_non_owner_cannot_access_store_categories(self):
        response = self.client.get(
            f"/api/categories/stores/{self.store.id}/categories/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_tenant_cannot_access_store_categories(self):
        response = self.client.get(
            f"/api/categories/stores/{self.store.id}/categories/",
            HTTP_AUTHORIZATION=self.other_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_store_not_found_returns_404(self):
        response = self.client.get(
            "/api/categories/stores/999999/categories/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_category_not_found_returns_404(self):
        response = self.client.get(
            f"/api/categories/stores/{self.store.id}/categories/999999/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)