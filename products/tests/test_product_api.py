from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store
from users.models import User


class ProductApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create(
            username="owner",
            email="owner@example.com",
            role="Store Owner",
            is_active=True,
            tenant_id=100,
        )
        self.owner.set_password("StrongPass123!")
        self.owner.save()

        self.same_tenant_non_owner = User.objects.create(
            username="same_tenant_non_owner",
            email="same_tenant_non_owner@example.com",
            role="Store Owner",
            is_active=True,
            tenant_id=100,
        )
        self.same_tenant_non_owner.set_password("StrongPass123!")
        self.same_tenant_non_owner.save()

        self.other_tenant_user = User.objects.create(
            username="other_tenant_user",
            email="other_tenant_user@example.com",
            role="Store Owner",
            is_active=True,
            tenant_id=200,
        )
        self.other_tenant_user.set_password("StrongPass123!")
        self.other_tenant_user.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Store A",
            tenant_id=100,
        )
        self.other_store_same_owner = Store.objects.create(
            owner=self.owner,
            name="Store B",
            tenant_id=100,
        )
        self.foreign_store = Store.objects.create(
            owner=self.other_tenant_user,
            name="Foreign Store",
            tenant_id=200,
        )

        self.category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Phones",
            description="Phones category",
        )
        self.other_store_category = Category.objects.create(
            store=self.other_store_same_owner,
            tenant_id=self.other_store_same_owner.tenant_id,
            name="Other Store Category",
            description="Should not be used in store A",
        )

        self.product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Wireless Mouse",
            description="Bluetooth mouse",
            price=Decimal("25.99"),
            sku="MOUSE-BT-001",
            category=self.category,
            status="active",
        )
        self.inventory = Inventory.objects.create(
            product=self.product,
            stock_quantity=12,
        )
        self.image = ProductImage.objects.create(
            product=self.product,
            image_url="https://example.com/initial.jpg",
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

    @staticmethod
    def _make_image_file(
        *,
        fmt: str,
        filename: str,
        content_type: str,
        size=(64, 64),
    ):
        buffer = BytesIO()
        Image.new("RGB", size, color=(255, 0, 0)).save(buffer, format=fmt)
        buffer.seek(0)
        return SimpleUploadedFile(filename, buffer.getvalue(), content_type=content_type)

    def _assert_product_shape(self, item):
        self.assertIn("id", item)
        self.assertIn("store_id", item)
        self.assertIn("category_id", item)
        self.assertIn("category_name", item)
        self.assertIn("name", item)
        self.assertIn("description", item)
        self.assertIn("price", item)
        self.assertIn("sku", item)
        self.assertIn("stock", item)
        self.assertIn("status", item)
        self.assertIn("image_url", item)
        self.assertIn("created_at", item)
        self.assertIn("updated_at", item)

    def _assert_image_shape(self, item):
        self.assertIn("id", item)
        self.assertIn("image_url", item)
        self.assertIn("created_at", item)
        self.assertIn("updated_at", item)

    # ---------------------------
    # Product endpoints
    # ---------------------------

    def test_list_products_returns_current_shape(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(len(payload), 1)

        item = payload[0]
        self._assert_product_shape(item)
        self.assertEqual(item["id"], self.product.id)
        self.assertEqual(item["store_id"], self.store.id)
        self.assertEqual(item["category_id"], self.category.id)
        self.assertEqual(item["category_name"], self.category.name)
        self.assertEqual(item["name"], "Wireless Mouse")
        self.assertEqual(item["description"], "Bluetooth mouse")
        self.assertIsInstance(item["price"], (int, float))
        self.assertEqual(item["stock"], 12)
        self.assertEqual(item["status"], "active")
        self.assertEqual(item["image_url"], "https://example.com/initial.jpg")

    def test_create_product_returns_current_shape(self):
        response = self.client.post(
            f"/api/products/{self.store.id}/products/",
            {
                "name": "Keyboard",
                "description": "Mechanical keyboard",
                "price": "50.00",
                "stock": 7,
                "status": "active",
                "category_id": self.category.id,
                "image_url": "https://example.com/keyboard.jpg",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["store_id"], self.store.id)
        self.assertEqual(payload["category_id"], self.category.id)
        self.assertEqual(payload["category_name"], self.category.name)
        self.assertEqual(payload["name"], "Keyboard")
        self.assertEqual(payload["description"], "Mechanical keyboard")
        self.assertEqual(payload["stock"], 7)
        self.assertEqual(payload["image_url"], "https://example.com/keyboard.jpg")

        product = Product.objects.get(id=payload["id"])
        self.assertTrue(bool(product.sku))
        self.assertEqual(product.category_id, self.category.id)
        self.assertEqual(product.inventory.stock_quantity, 7)

    def test_create_product_rejects_category_from_another_store(self):
        response = self.client.post(
            f"/api/products/{self.store.id}/products/",
            {
                "name": "Cross Store Product",
                "description": "Should fail",
                "price": "19.99",
                "status": "active",
                "category_id": self.other_store_category.id,
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("detail", payload)
        self.assertIn("Category does not belong to this store", payload["detail"])

    def test_retrieve_product_returns_current_shape(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["id"], self.product.id)
        self.assertEqual(payload["store_id"], self.store.id)
        self.assertEqual(payload["category_id"], self.category.id)
        self.assertEqual(payload["stock"], 12)
        self.assertEqual(payload["image_url"], "https://example.com/initial.jpg")

    def test_patch_product_returns_current_shape(self):
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {"name": "Patched Mouse"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["name"], "Patched Mouse")
        self.assertEqual(payload["stock"], 12)

        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Patched Mouse")

    def test_patch_product_accepts_stock_and_image_url(self):
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {
                "stock": 3,
                "image_url": "https://example.com/patched-mouse.jpg",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["stock"], 3)
        self.assertEqual(payload["image_url"], "https://example.com/patched-mouse.jpg")

        self.product.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 3)
        self.assertTrue(
            ProductImage.objects.filter(
                product=self.product,
                image_url="https://example.com/patched-mouse.jpg",
            ).exists()
        )

    def test_patch_product_accepts_zero_stock(self):
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {"stock": 0},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["stock"], 0)

        self.product.refresh_from_db()
        self.assertEqual(self.product.inventory.stock_quantity, 0)

    def test_put_product_returns_current_shape(self):
        category_b = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Accessories",
            description="Accessories category",
        )

        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {
                "name": "Updated Mouse",
                "description": "Updated description",
                "price": "58.00",
                "sku": "UPDATED-001",
                "status": "out_of_stock",
                "category_id": category_b.id,
                "stock": 5,
                "image_url": "https://example.com/updated-mouse.jpg",
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self._assert_product_shape(payload)
        self.assertEqual(payload["name"], "Updated Mouse")
        self.assertEqual(payload["category_id"], category_b.id)
        self.assertEqual(payload["category_name"], "Accessories")
        self.assertEqual(payload["status"], "out_of_stock")
        self.assertEqual(payload["stock"], 5)
        self.assertEqual(payload["image_url"], "https://example.com/updated-mouse.jpg")

    def test_put_requires_full_payload(self):
        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {"name": "Only Name Sent"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertTrue(isinstance(payload, dict))
        self.assertTrue(any(key in payload for key in ["description", "price", "sku", "status"]))

    def test_delete_product_success(self):
        response = self.client.delete(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(id=self.product.id).exists())

    # ---------------------------
    # Images endpoints
    # ---------------------------

    def test_list_product_images_returns_current_shape(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(len(payload), 1)
        self._assert_image_shape(payload[0])
        self.assertEqual(payload[0]["image_url"], "https://example.com/initial.jpg")

    def test_upload_image_file_returns_current_shape(self):
        image_file = self._make_image_file(
            fmt="PNG",
            filename="valid.png",
            content_type="image/png",
        )

        response = self.client.post(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/",
            {"image_file": image_file},
            format="multipart",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = self._payload(response)
        self._assert_image_shape(payload)
        self.assertIsNotNone(payload["image_url"])

    def test_invalid_image_format_rejected(self):
        bmp_file = self._make_image_file(
            fmt="BMP",
            filename="invalid.bmp",
            content_type="image/bmp",
        )

        response = self.client.post(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/",
            {"image_file": bmp_file},
            format="multipart",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        payload = self._payload(response)
        self.assertIn("image_file", payload)

    def test_delete_product_image_success(self):
        response = self.client.delete(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/{self.image.id}/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProductImage.objects.filter(id=self.image.id).exists())

    # ---------------------------
    # Inventory endpoint
    # ---------------------------

    def test_update_inventory_success(self):
        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/inventory/",
            {"stock_quantity": 99},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIn("id", payload)
        self.assertEqual(payload["stock_quantity"], 99)
        self.assertIn("created_at", payload)
        self.assertIn("updated_at", payload)

        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.stock_quantity, 99)

    # ---------------------------
    # Authorization / isolation
    # ---------------------------

    def test_non_owner_same_tenant_cannot_access_store_products(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_tenant_cannot_access_store_products(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/",
            HTTP_AUTHORIZATION=self.other_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_owner_same_tenant_cannot_update_product(self):
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/",
            {"name": "Compromised Name"},
            format="json",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_owner_same_tenant_cannot_update_inventory(self):
        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/inventory/",
            {"stock_quantity": 999},
            format="json",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_owner_same_tenant_cannot_upload_image(self):
        image_file = self._make_image_file(
            fmt="PNG",
            filename="blocked.png",
            content_type="image/png",
        )

        response = self.client.post(
            f"/api/products/{self.store.id}/products/{self.product.id}/images/",
            {"image_file": image_file},
            format="multipart",
            HTTP_AUTHORIZATION=self.same_tenant_auth,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_price_rejected(self):
        response = self.client.post(
            f"/api/products/{self.store.id}/products/",
            {
                "name": "Bad Product",
                "description": "Should fail",
                "price": "-1.00",
                "status": "active",
                "category_id": self.category.id,
            },
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
