from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from stores.models import Store
from categories.models import Category
from categories import services, selectors
from products.models import Product

User = get_user_model()


class CategoryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            tenant_id=1,
        )
        self.store = Store.objects.create(
            owner=self.user,
            name="Test Store",
            tenant_id=1,
        )

    def test_category_creation(self):
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
            description="Electronic devices",
        )
        self.assertEqual(category.name, "Electronics")
        self.assertEqual(category.store, self.store)
        self.assertEqual(category.tenant_id, 1)

    def test_category_unique_name_per_store(self):
        Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
        )
        with self.assertRaises(Exception):
            Category.objects.create(
                store=self.store,
                tenant_id=self.store.tenant_id,
                name="Electronics",
            )

    def test_same_name_different_stores(self):
        store2 = Store.objects.create(
            owner=self.user,
            name="Test Store 2",
            tenant_id=2,
        )

        cat1 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
        )
        cat2 = Category.objects.create(
            store=store2,
            tenant_id=store2.tenant_id,
            name="Electronics",
        )

        self.assertEqual(cat1.name, cat2.name)
        self.assertNotEqual(cat1.store, cat2.store)

    def test_category_tenant_id_auto_set(self):
        category = Category.objects.create(
            store=self.store,
            name="Test Category",
        )
        self.assertEqual(category.tenant_id, self.store.tenant_id)

    def test_category_str_representation(self):
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
        )
        self.assertEqual(str(category), f"Electronics (Store: {self.store.name})")


class CategoryServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            tenant_id=1,
        )
        self.store = Store.objects.create(
            owner=self.user,
            name="Test Store",
            tenant_id=1,
        )

    def test_create_category_valid(self):
        category = services.create_category(
            store=self.store,
            name="Electronics",
            description="Electronic devices",
            user=self.user,
        )
        self.assertIsNotNone(category.id)
        self.assertEqual(category.name, "Electronics")
        self.assertEqual(category.description, "Electronic devices")
        self.assertEqual(category.tenant_id, self.store.tenant_id)

    def test_create_category_empty_name(self):
        with self.assertRaises(ValidationError):
            services.create_category(
                store=self.store,
                name="",
                user=self.user,
            )

    def test_create_category_duplicate_name(self):
        services.create_category(
            store=self.store,
            name="Electronics",
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            services.create_category(
                store=self.store,
                name="Electronics",
                user=self.user,
            )

    def test_update_category_valid(self):
        category = services.create_category(
            store=self.store,
            name="Electronics",
            user=self.user,
        )

        updated = services.update_category(
            category=category,
            name="Home Appliances",
            description="Appliances for the home",
            user=self.user,
        )

        self.assertEqual(updated.name, "Home Appliances")
        self.assertEqual(updated.description, "Appliances for the home")

    def test_update_category_empty_name(self):
        category = services.create_category(
            store=self.store,
            name="Electronics",
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            services.update_category(
                category=category,
                name="",
                user=self.user,
            )

    def test_delete_category(self):
        category = services.create_category(
            store=self.store,
            name="Electronics",
            user=self.user,
        )
        category_id = category.id

        result = services.delete_category(category, user=self.user)

        self.assertTrue(result)
        self.assertFalse(Category.objects.filter(id=category_id).exists())

    def test_delete_category_with_linked_products_blocked(self):
        category = services.create_category(
            store=self.store,
            name="Electronics",
            user=self.user,
        )

        Product.objects.create(
            store=self.store,
            category=category,
            name="Phone",
            description="Smart phone",
            price=999.99,
            sku="PHONE-001",
            tenant_id=self.store.tenant_id,
        )

        with self.assertRaises(ValidationError) as exc:
            services.delete_category(category, user=self.user)

        self.assertIn("Cannot delete category with assigned products", str(exc.exception))
        self.assertTrue(Category.objects.filter(id=category.id).exists())


class CategorySelectorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            tenant_id=1,
        )
        self.store = Store.objects.create(
            owner=self.user,
            name="Test Store",
            tenant_id=1,
        )
        self.cat1 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Electronics",
        )
        self.cat2 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Clothing",
        )

    def test_get_store_categories(self):
        categories = selectors.get_store_categories(self.store)
        self.assertEqual(categories.count(), 2)
        self.assertIn(self.cat1, categories)
        self.assertIn(self.cat2, categories)

    def test_get_category_by_id(self):
        category = selectors.get_category_by_id(self.cat1.id, self.store)
        self.assertEqual(category.id, self.cat1.id)
        self.assertEqual(category.name, "Electronics")

    def test_get_category_by_id_wrong_store(self):
        from django.core.exceptions import ObjectDoesNotExist

        store2 = Store.objects.create(
            owner=self.user,
            name="Test Store 2",
            tenant_id=2,
        )

        with self.assertRaises(ObjectDoesNotExist):
            selectors.get_category_by_id(self.cat1.id, store2)

    def test_get_category_by_name(self):
        category = selectors.get_category_by_name(self.store, "Electronics")
        self.assertIsNotNone(category)
        self.assertEqual(category.name, "Electronics")

    def test_get_category_by_name_nonexistent(self):
        category = selectors.get_category_by_name(self.store, "Nonexistent")
        self.assertIsNone(category)

    def test_check_category_has_products(self):
        self.assertFalse(selectors.check_category_has_products(self.cat1))

        Product.objects.create(
            store=self.store,
            category=self.cat1,
            name="Laptop",
            description="Laptop product",
            price=1200.00,
            sku="LAPTOP-001",
            tenant_id=self.store.tenant_id,
        )

        self.assertTrue(selectors.check_category_has_products(self.cat1))