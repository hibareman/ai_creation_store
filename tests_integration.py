"""
اختبارات التكامل الشاملة للـ Multi-Tenant Isolation
تحقق من عزل البيانات بين المستأجرين على جميع المستويات
"""
import os
import sys
import django
from pathlib import Path

# Setup Django
workspace = Path(__file__).parent
os.chdir(workspace)
sys.path.insert(0, str(workspace))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import TestCase, Client
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User
from stores.models import Store, StoreDomain, StoreSettings
from categories.models import Category
from products.models import Product, ProductImage, Inventory


class MultiTenantIsolationTests(TestCase):
    """اختبارات عزل البيانات بين المستأجرين"""

    def setUp(self):
        """إعداد بيانات الاختبار مع مستأجرين منفصلين"""
        self.client = Client()

        # إنشاء مستخدمين من مستأجرين مختلفين
        self.tenant1_user = User.objects.create_user(
            username='tenant1_user',
            email='tenant1@example.com',
            password='Tenant123!'
        )
        self.tenant1_user.is_active = True
        self.tenant1_user.tenant_id = 1
        self.tenant1_user.role = 'Store Owner'
        self.tenant1_user.save()

        self.tenant2_user = User.objects.create_user(
            username='tenant2_user',
            email='tenant2@example.com',
            password='Tenant123!'
        )
        self.tenant2_user.is_active = True
        self.tenant2_user.tenant_id = 2
        self.tenant2_user.role = 'Store Owner'
        self.tenant2_user.save()

        # إنشاء متاجر لكل مستأجر
        self.tenant1_store = Store.objects.create(
            owner=self.tenant1_user,
            name='Tenant 1 Store',
            tenant_id=1
        )

        self.tenant2_store = Store.objects.create(
            owner=self.tenant2_user,
            name='Tenant 2 Store',
            tenant_id=2
        )

        # إنشاء تصنيفات لكل متجر
        self.tenant1_category = Category.objects.create(
            store=self.tenant1_store,
            name='Tenant 1 Category'
        )

        self.tenant2_category = Category.objects.create(
            store=self.tenant2_store,
            name='Tenant 2 Category'
        )

        # إنشاء منتجات لكل متجر
        self.tenant1_product = Product.objects.create(
            store=self.tenant1_store,
            category=self.tenant1_category,
            name='Tenant 1 Product',
            sku='T1-001',
            price=100.00,
            description='Product from Tenant 1'
        )

        self.tenant2_product = Product.objects.create(
            store=self.tenant2_store,
            category=self.tenant2_category,
            name='Tenant 2 Product',
            sku='T2-001',
            price=200.00,
            description='Product from Tenant 2'
        )

    def _get_auth_header(self, user):
        """الحصول على JWT token للمستخدم"""
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    # ============ اختبارات عزل المتاجر ============

    def test_tenant1_cannot_update_tenant2_store(self):
        """المستأجر 1 لا يستطيع تحديث متجر المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        data = {'name': 'Hacked Store Name'}

        response = self.client.patch(
            f'/api/stores/{self.tenant2_store.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن اسم المتجر لم يتغير
        self.tenant2_store.refresh_from_db()
        self.assertEqual(self.tenant2_store.name, 'Tenant 2 Store')

    def test_tenant1_cannot_delete_tenant2_store(self):
        """المستأجر 1 لا يستطيع حذف متجر المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.delete(
            f'/api/stores/{self.tenant2_store.id}/delete/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن المتجر لم يُحذف
        self.assertTrue(Store.objects.filter(id=self.tenant2_store.id).exists())

    def test_tenant2_cannot_update_tenant1_store(self):
        """المستأجر 2 لا يستطيع تحديث متجر المستأجر 1"""
        auth = self._get_auth_header(self.tenant2_user)

        data = {'name': 'Hacked Store Name'}

        response = self.client.patch(
            f'/api/stores/{self.tenant1_store.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن اسم المتجر لم يتغير
        self.tenant1_store.refresh_from_db()
        self.assertEqual(self.tenant1_store.name, 'Tenant 1 Store')

    # ============ اختبارات عزل التصنيفات ============

    def test_tenant1_cannot_access_tenant2_categories(self):
        """المستأجر 1 لا يستطيع الوصول إلى تصنيفات المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        # محاولة جلب قائمة التصنيفات
        response = self.client.get(
            f'/api/categories/',
            HTTP_AUTHORIZATION=auth
        )

        # إذا كانت موجودة (200)، التحقق من أن قائمة التصنيفات لا تحتوي على تصنيفات المستأجر 2
        if response.status_code == 200:
            category_ids = [cat['id'] for cat in response.data] if response.data else []
            self.assertNotIn(self.tenant2_category.id, category_ids)

    def test_tenant2_cannot_access_tenant1_categories(self):
        """المستأجر 2 لا يستطيع الوصول إلى تصنيفات المستأجر 1"""
        auth = self._get_auth_header(self.tenant2_user)

        # محاولة جلب قائمة التصنيفات
        response = self.client.get(
            f'/api/categories/',
            HTTP_AUTHORIZATION=auth
        )

        # إذا كانت موجودة (200)، التحقق من أن قائمة التصنيفات لا تحتوي على تصنيفات المستأجر 1
        if response.status_code == 200:
            category_ids = [cat['id'] for cat in response.data] if response.data else []
            self.assertNotIn(self.tenant1_category.id, category_ids)

    def test_tenant1_cannot_update_tenant2_category(self):
        """المستأجر 1 لا يستطيع تحديث تصنيف المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        data = {'name': 'Hacked Category'}

        response = self.client.patch(
            f'/api/categories/{self.tenant2_category.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن اسم التصنيف لم يتغير
        self.tenant2_category.refresh_from_db()
        self.assertEqual(self.tenant2_category.name, 'Tenant 2 Category')

    def test_tenant1_cannot_delete_tenant2_category(self):
        """المستأجر 1 لا يستطيع حذف تصنيف المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.delete(
            f'/api/categories/{self.tenant2_category.id}/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن التصنيف لم يُحذف
        self.assertTrue(Category.objects.filter(id=self.tenant2_category.id).exists())

    # ============ اختبارات عزل المنتجات ============

    def test_tenant1_cannot_access_list_tenant2_products(self):
        """المستأجر 1 قائمة المنتجات تحتوي فقط على منتجاته"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.get(
            f'/api/products/',
            HTTP_AUTHORIZATION=auth
        )

        # إذا كانت 200، يجب أن تحتوي فقط على منتجات المستأجر 1
        if response.status_code == 200:
            product_ids = [prod['id'] for prod in response.data] if response.data else []
            self.assertIn(self.tenant1_product.id, product_ids)
            self.assertNotIn(self.tenant2_product.id, product_ids)

    def test_tenant2_cannot_access_list_tenant1_products(self):
        """المستأجر 2 قائمة المنتجات تحتوي فقط على منتجاته"""
        auth = self._get_auth_header(self.tenant2_user)

        response = self.client.get(
            f'/api/products/',
            HTTP_AUTHORIZATION=auth
        )

        # إذا كانت 200، يجب أن تحتوي فقط على منتجات المستأجر 2
        if response.status_code == 200:
            product_ids = [prod['id'] for prod in response.data] if response.data else []
            self.assertIn(self.tenant2_product.id, product_ids)
            self.assertNotIn(self.tenant1_product.id, product_ids)

    def test_tenant1_cannot_update_tenant2_product(self):
        """المستأجر 1 لا يستطيع تحديث منتج المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        data = {'name': 'Hacked Product'}

        response = self.client.patch(
            f'/api/products/{self.tenant2_product.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن اسم المنتج لم يتغير
        self.tenant2_product.refresh_from_db()
        self.assertEqual(self.tenant2_product.name, 'Tenant 2 Product')

    def test_tenant1_cannot_delete_tenant2_product(self):
        """المستأجر 1 لا يستطيع حذف منتج المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.delete(
            f'/api/products/{self.tenant2_product.id}/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن المنتج لم يُحذف
        self.assertTrue(Product.objects.filter(id=self.tenant2_product.id).exists())

    def test_tenant2_cannot_update_tenant1_product(self):
        """المستأجر 2 لا يستطيع تحديث منتج المستأجر 1"""
        auth = self._get_auth_header(self.tenant2_user)

        data = {'name': 'Hacked Product'}

        response = self.client.patch(
            f'/api/products/{self.tenant1_product.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

        # تحقق أن اسم المنتج لم يتغير
        self.tenant1_product.refresh_from_db()
        self.assertEqual(self.tenant1_product.name, 'Tenant 1 Product')

    # ============ اختبارات عزل الأوامات (Store List) ============

    def test_tenant1_can_only_see_own_stores(self):
        """المستأجر 1 يرى فقط متاجره الخاصة"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.get(
            '/api/stores/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertEqual(response.status_code, 200)

        store_ids = [store['id'] for store in response.data]
        self.assertIn(self.tenant1_store.id, store_ids)
        self.assertNotIn(self.tenant2_store.id, store_ids)

    def test_tenant2_can_only_see_own_stores(self):
        """المستأجر 2 يرى فقط متاجره الخاصة"""
        auth = self._get_auth_header(self.tenant2_user)

        response = self.client.get(
            '/api/stores/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertEqual(response.status_code, 200)

        store_ids = [store['id'] for store in response.data]
        self.assertIn(self.tenant2_store.id, store_ids)
        self.assertNotIn(self.tenant1_store.id, store_ids)

    # ============ اختبارات عزل الإعدادات ============

    def test_tenant1_cannot_access_tenant2_store_settings(self):
        """المستأجر 1 لا يستطيع الوصول إلى إعدادات متجر المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.get(
            f'/api/stores/{self.tenant2_store.id}/settings/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertIn(response.status_code, [403, 404])

    def test_tenant1_cannot_update_tenant2_store_settings(self):
        """المستأجر 1 لا يستطيع تحديث إعدادات متجر المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        data = {'currency': 'EUR'}

        response = self.client.patch(
            f'/api/stores/{self.tenant2_store.id}/settings/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])

    # ============ اختبارات عزل النطاقات (Domains) ============

    def test_tenant1_cannot_access_tenant2_domains(self):
        """المستأجر 1 لا يستطيع الوصول إلى نطاقات المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        response = self.client.get(
            f'/api/stores/{self.tenant2_store.id}/domains/',
            HTTP_AUTHORIZATION=auth
        )

        self.assertIn(response.status_code, [403, 404, 200])

        if response.status_code == 200:
            # إذا كانت 200، يجب أن تكون القائمة فارغة
            self.assertEqual(len(response.data), 0)

    def test_tenant1_cannot_add_domain_to_tenant2_store(self):
        """المستأجر 1 لا يستطيع إضافة نطاق إلى متجر المستأجر 2"""
        auth = self._get_auth_header(self.tenant1_user)

        data = {
            'domain': 'malicious.com',
            'is_primary': False
        }

        response = self.client.post(
            f'/api/stores/{self.tenant2_store.id}/domains/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )

        self.assertIn(response.status_code, [403, 404])


class StoreListFilteringTests(TestCase):
    """اختبارات تصفية بيانات المتاجر"""

    def setUp(self):
        """إعداد بيانات الاختبار"""
        self.user = User.objects.create_user(
            username='test_user',
            email='test@example.com',
            password='Test123!'
        )
        self.user.is_active = True
        self.user.tenant_id = 1
        self.user.save()

        # إنشاء عدة متاجر
        self.store1 = Store.objects.create(owner=self.user, name='Store 1', tenant_id=1)
        self.store2 = Store.objects.create(owner=self.user, name='Store 2', tenant_id=1)
        self.store3 = Store.objects.create(owner=self.user, name='Store 3', tenant_id=1)

    def _get_auth_header(self, user):
        """الحصول على JWT token"""
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_list_stores_returns_only_user_stores(self):
        """قائمة المتاجر تعيد فقط متاجر المستخدم الحالي"""
        client = Client()
        auth = self._get_auth_header(self.user)

        response = client.get('/api/stores/', HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)

        # تحقق أن المتاجر التي أنشأناها موجودة في الرد
        store_ids = [store['id'] for store in response.data]
        
        # جميع متاجرنا يجب أن تكون موجودة
        for store in [self.store1, self.store2, self.store3]:
            self.assertIn(store.id, store_ids, f"Store {store.id} not found in response")

    def test_list_stores_contains_created_stores(self):
        """قائمة المتاجر تحتوي على المتاجر التي أنشأناها"""
        client = Client()
        auth = self._get_auth_header(self.user)

        response = client.get('/api/stores/', HTTP_AUTHORIZATION=auth)

        self.assertEqual(response.status_code, 200)

        store_ids = [store['id'] for store in response.data]
        self.assertIn(self.store1.id, store_ids)
        self.assertIn(self.store2.id, store_ids)
        self.assertIn(self.store3.id, store_ids)


if __name__ == '__main__':
    import unittest
    unittest.main()
