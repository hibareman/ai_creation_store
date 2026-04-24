from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from decimal import Decimal

from categories.models import Category
from products.models import Product
from seo.models import CategorySEO, ProductSEO, StoreSEO
from stores.models import Store
from users.models import User


class SEOAPITestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="owner",
            email="owner@test.com",
            password="pass123",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 100
        self.owner.save()

        self.same_tenant_non_owner = User.objects.create_user(
            username="same_tenant",
            email="same@test.com",
            password="pass123",
        )
        self.same_tenant_non_owner.is_active = True
        self.same_tenant_non_owner.tenant_id = 100
        self.same_tenant_non_owner.save()

        self.cross_tenant_user = User.objects.create_user(
            username="cross_tenant",
            email="cross@test.com",
            password="pass123",
        )
        self.cross_tenant_user.is_active = True
        self.cross_tenant_user.tenant_id = 200
        self.cross_tenant_user.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Main Store",
            description="Main store description",
            status="active",
            tenant_id=self.owner.tenant_id,
        )

        self.category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
            description="Electronics category description",
        )

        # ✅ Use Decimal for price, not string
        self.product = Product.objects.create(
            store=self.store,
            category=self.category,
            tenant_id=self.store.tenant_id,
            name="Wireless Mouse",
            description="Wireless mouse description",
            price=Decimal("49.99"),
            sku="MOUSE-001",
            status="active",
        )

    def auth(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @staticmethod
    def payload(response):
        return response.json()


class StoreSEOTests(SEOAPITestBase):
    """اختبارات SEO للمتجر"""

    def test_owner_can_get_store_seo(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/stores/{self.store.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_update_store_seo_with_put(self):
        self.auth(self.owner)
        response = self.client.put(
            f"/api/stores/{self.store.id}/seo/",
            {"seo": {"metaTitle": "Store SEO Title", "metaDescription": "Store SEO Desc"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Store SEO Title")
        self.assertEqual(data["seo"]["metaDescription"], "Store SEO Desc")

    def test_owner_can_partial_update_store_seo_with_patch(self):
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/stores/{self.store.id}/seo/",
            {"seo": {"metaTitle": "Updated Store Title"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Updated Store Title")

    def test_unauthenticated_store_seo_returns_401(self):
        response = self.client.get(f"/api/stores/{self.store.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_same_tenant_non_owner_cannot_access_store_seo(self):
        self.auth(self.same_tenant_non_owner)
        response = self.client.get(f"/api/stores/{self.store.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_user_gets_404_for_store_seo(self):
        self.auth(self.cross_tenant_user)
        response = self.client.get(f"/api/stores/{self.store.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_store_seo_fallback_uses_store_name_and_description(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/stores/{self.store.id}/seo/")
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], self.store.name)
        self.assertEqual(data["seo"]["metaDescription"], self.store.description)

    def test_store_seo_patch_creates_seo_record_when_missing(self):
        self.assertFalse(StoreSEO.objects.filter(store=self.store).exists())
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/stores/{self.store.id}/seo/",
            {"seo": {"metaKeywords": "store,shop"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(StoreSEO.objects.filter(store=self.store).exists())


class ProductSEOTests(SEOAPITestBase):
    """اختبارات SEO للمنتج"""

    def test_owner_can_get_product_seo(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/products/{self.store.id}/products/{self.product.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_update_product_seo_with_put(self):
        self.auth(self.owner)
        response = self.client.put(
            f"/api/products/{self.store.id}/products/{self.product.id}/seo/",
            {"seo": {"metaTitle": "Product SEO Title", "metaDescription": "Product SEO Desc"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Product SEO Title")
        self.assertEqual(data["seo"]["metaDescription"], "Product SEO Desc")

    def test_owner_can_partial_update_product_seo_with_patch(self):
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/seo/",
            {"seo": {"metaTitle": "Updated Product Title"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Updated Product Title")

    def test_unauthenticated_product_seo_returns_401(self):
        response = self.client.get(f"/api/products/{self.store.id}/products/{self.product.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_same_tenant_non_owner_cannot_access_product_seo(self):
        self.auth(self.same_tenant_non_owner)
        response = self.client.get(f"/api/products/{self.store.id}/products/{self.product.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_user_gets_404_for_product_seo(self):
        self.auth(self.cross_tenant_user)
        response = self.client.get(f"/api/products/{self.store.id}/products/{self.product.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_product_seo_fallback_uses_product_name_and_description(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/products/{self.store.id}/products/{self.product.id}/seo/")
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], self.product.name)
        self.assertEqual(data["seo"]["metaDescription"], self.product.description)

    def test_product_seo_patch_creates_seo_record_when_missing(self):
        self.assertFalse(ProductSEO.objects.filter(product=self.product).exists())
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/seo/",
            {"seo": {"metaKeywords": "mouse,wireless"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ProductSEO.objects.filter(product=self.product).exists())


class CategorySEOTests(SEOAPITestBase):
    """اختبارات SEO للتصنيف"""

    def test_owner_can_get_category_seo(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_can_update_category_seo_with_put(self):
        self.auth(self.owner)
        response = self.client.put(
            f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/",
            {"seo": {"metaTitle": "Category SEO Title", "metaDescription": "Category SEO Desc"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Category SEO Title")
        self.assertEqual(data["seo"]["metaDescription"], "Category SEO Desc")

    def test_owner_can_partial_update_category_seo_with_patch(self):
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/",
            {"seo": {"metaTitle": "Updated Category Title"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], "Updated Category Title")

    def test_unauthenticated_category_seo_returns_401(self):
        response = self.client.get(f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_same_tenant_non_owner_cannot_access_category_seo(self):
        self.auth(self.same_tenant_non_owner)
        response = self.client.get(f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_user_gets_404_for_category_seo(self):
        self.auth(self.cross_tenant_user)
        response = self.client.get(f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_category_seo_fallback_uses_category_name_and_description(self):
        self.auth(self.owner)
        response = self.client.get(f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/")
        data = self.payload(response)
        self.assertEqual(data["seo"]["metaTitle"], self.category.name)
        self.assertEqual(data["seo"]["metaDescription"], self.category.description)

    def test_category_seo_patch_creates_seo_record_when_missing(self):
        self.assertFalse(CategorySEO.objects.filter(category=self.category).exists())
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/categories/{self.store.id}/categories/{self.category.id}/seo/",
            {"seo": {"metaKeywords": "electronics,gadgets"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(CategorySEO.objects.filter(category=self.category).exists())


class SEOFieldMappingTests(SEOAPITestBase):
    """اختبارات تحويل أسماء الحقول بين الـ API والنموذج"""

    def test_store_seo_field_mapping(self):
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/stores/{self.store.id}/seo/",
            {
                "seo": {
                    "metaTitle": "Test Title",
                    "metaDescription": "Test Description",
                    "metaKeywords": "test,keywords",
                    "ogTitle": "OG Title",
                    "ogDescription": "OG Description",
                    "ogImageUrl": "https://example.com/image.jpg",
                    "canonicalUrl": "https://example.com/canonical",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        seo_obj = StoreSEO.objects.get(store=self.store)
        self.assertEqual(seo_obj.meta_title, "Test Title")
        self.assertEqual(seo_obj.meta_description, "Test Description")
        self.assertEqual(seo_obj.meta_keywords, "test,keywords")
        self.assertEqual(seo_obj.og_title, "OG Title")
        self.assertEqual(seo_obj.og_description, "OG Description")
        self.assertEqual(seo_obj.og_image_url, "https://example.com/image.jpg")
        self.assertEqual(seo_obj.canonical_url, "https://example.com/canonical")

    def test_product_seo_field_mapping(self):
        self.auth(self.owner)
        response = self.client.patch(
            f"/api/products/{self.store.id}/products/{self.product.id}/seo/",
            {
                "seo": {
                    "metaTitle": "Product Test Title",
                    "metaDescription": "Product Test Description",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        seo_obj = ProductSEO.objects.get(product=self.product)
        self.assertEqual(seo_obj.meta_title, "Product Test Title")
        self.assertEqual(seo_obj.meta_description, "Product Test Description")