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

    @staticmethod
    def _product_ids(payload):
        return {item["id"] for item in payload}

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

    def test_product_search_returns_matching_results(self):
        matching_foreign_product = Product.objects.create(
            store=self.other_store_same_owner,
            tenant_id=self.other_store_same_owner.tenant_id,
            name="Wireless Mouse Other Store",
            description="Should not leak across store scope",
            price=Decimal("30.00"),
            sku="OTHER-MOUSE-001",
            category=self.other_store_category,
            status="active",
        )
        Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Mechanical Keyboard",
            description="Different product",
            price=Decimal("80.00"),
            sku="KEYBOARD-001",
            category=self.category,
            status="active",
        )

        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search= wireless ",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertEqual(self._product_ids(payload), {self.product.id})
        self.assertNotIn(matching_foreign_product.id, self._product_ids(payload))

    def test_product_search_with_no_results_returns_empty_list(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search=not-found",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response), [])

    def test_product_filtering_by_category(self):
        accessories = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Accessories",
            description="Accessories category",
        )
        accessory_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="USB Hub",
            description="Multi-port hub",
            price=Decimal("18.00"),
            sku="USB-HUB-001",
            category=accessories,
            status="active",
        )

        response = self.client.get(
            f"/api/products/{self.store.id}/products/?category_id={accessories.id}",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(response)), {accessory_product.id})

    def test_combined_product_search_and_category_filtering(self):
        accessories = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Accessories",
            description="Accessories category",
        )
        mouse_pad = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Mouse Pad",
            description="Desk mat",
            price=Decimal("12.00"),
            sku="MOUSE-PAD-001",
            category=accessories,
            status="active",
        )
        Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Keyboard Case",
            description="Carry case",
            price=Decimal("15.00"),
            sku="KEY-CASE-001",
            category=accessories,
            status="active",
        )

        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search=mouse&category_id={accessories.id}",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(response)), {mouse_pad.id})

    def test_product_filtering_invalid_category_id_returns_400(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?category_id=999999",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category_id", self._payload(response))

    def test_product_filtering_category_from_another_store_returns_400(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?category_id={self.other_store_category.id}",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category_id", self._payload(response))

    def test_product_filters_keep_tenant_and_store_isolation(self):
        Product.objects.create(
            store=self.other_store_same_owner,
            tenant_id=self.other_store_same_owner.tenant_id,
            name="Store Scoped Exclusive",
            description="Same owner and tenant, different store",
            price=Decimal("22.00"),
            sku="OTHER-STORE-EXCLUSIVE",
            category=self.other_store_category,
            status="active",
        )

        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search=exclusive",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response), [])

    def test_product_list_empty_store_data(self):
        empty_store = Store.objects.create(
            owner=self.owner,
            name="Empty Product Store",
            tenant_id=self.owner.tenant_id,
        )

        response = self.client.get(
            f"/api/products/{empty_store.id}/products/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response), [])

    def test_product_reset_filters_returns_complete_store_scoped_list(self):
        second_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Mechanical Keyboard",
            description="Different product",
            price=Decimal("80.00"),
            sku="KEYBOARD-002",
            category=self.category,
            status="active",
        )

        filtered = self.client.get(
            f"/api/products/{self.store.id}/products/?search=wireless",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        reset = self.client.get(
            f"/api/products/{self.store.id}/products/",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(reset.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(filtered)), {self.product.id})
        self.assertEqual(self._product_ids(self._payload(reset)), {self.product.id, second_product.id})
        self.assertIsInstance(self._payload(reset), list)

    def test_existing_pagination_behavior_remains_current_list_shape(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search=wireless",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        self.assertIsInstance(payload, list)
        self.assertNotIsInstance(payload, dict)
        self.assertEqual(self._product_ids(payload), {self.product.id})

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

    def test_product_search_matches_sku(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?search=mouse-bt",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(response)), {self.product.id})

    def test_product_filtering_by_every_supported_status(self):
        draft_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Draft Product",
            description="Draft",
            price=Decimal("15.00"),
            sku="DRAFT-001",
            category=self.category,
            status="draft",
        )
        out_of_stock_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Unavailable Product",
            description="Unavailable",
            price=Decimal("20.00"),
            sku="OUT-001",
            category=self.category,
            status="out_of_stock",
        )

        expected = {
            "active": self.product.id,
            "draft": draft_product.id,
            "out_of_stock": out_of_stock_product.id,
        }
        for status_value, product_id in expected.items():
            response = self.client.get(
                f"/api/products/{self.store.id}/products/?status={status_value}",
                HTTP_AUTHORIZATION=self.owner_auth,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(self._product_ids(self._payload(response)), {product_id})

    def test_product_filtering_unsupported_status_returns_400(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?status=inactive",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", self._payload(response))

    def test_product_filtering_by_stock_status(self):
        zero_stock_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Zero Stock",
            description="No stock",
            price=Decimal("10.00"),
            sku="ZERO-001",
            category=self.category,
            status="out_of_stock",
        )
        Inventory.objects.create(product=zero_stock_product, stock_quantity=0)

        no_inventory_product = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Missing Inventory",
            description="No inventory row",
            price=Decimal("11.00"),
            sku="NO-INV-001",
            category=self.category,
            status="draft",
        )

        in_stock = self.client.get(
            f"/api/products/{self.store.id}/products/?stock_status=in_stock",
            HTTP_AUTHORIZATION=self.owner_auth,
        )
        out_of_stock = self.client.get(
            f"/api/products/{self.store.id}/products/?stock_status=out_of_stock",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(in_stock.status_code, status.HTTP_200_OK)
        self.assertEqual(out_of_stock.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(in_stock)), {self.product.id})
        self.assertEqual(
            self._product_ids(self._payload(out_of_stock)),
            {zero_stock_product.id, no_inventory_product.id},
        )

    def test_product_filtering_unsupported_stock_status_returns_400(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?stock_status=low_stock",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("stock_status", self._payload(response))

    def test_product_ordering_by_price(self):
        cheaper = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Cheaper Product",
            description="Cheaper",
            price=Decimal("5.00"),
            sku="CHEAP-001",
            category=self.category,
            status="active",
        )

        response = self.client.get(
            f"/api/products/{self.store.id}/products/?ordering=price",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in self._payload(response)],
            [cheaper.id, self.product.id],
        )

    def test_product_unsupported_ordering_returns_400(self):
        response = self.client.get(
            f"/api/products/{self.store.id}/products/?ordering=stock",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ordering", self._payload(response))

    def test_product_combines_expanded_search_filters(self):
        matching = Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Premium Keyboard",
            description="Matching product",
            price=Decimal("90.00"),
            sku="PREMIUM-KEY-001",
            category=self.category,
            status="draft",
        )
        Inventory.objects.create(product=matching, stock_quantity=4)

        response = self.client.get(
            f"/api/products/{self.store.id}/products/"
            "?search=premium-key&status=draft&stock_status=in_stock&ordering=name",
            HTTP_AUTHORIZATION=self.owner_auth,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._product_ids(self._payload(response)), {matching.id})

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
