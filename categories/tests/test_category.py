from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from stores.models import Store
from categories.models import Category
from categories import services, selectors

User = get_user_model()


class CategoryModelTests(TestCase):
    """Test Category model functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            tenant_id=1
        )
        
        self.store = Store.objects.create(
            owner=self.user,
            name='Test Store',
            tenant_id=1
        )
    
    def test_category_creation(self):
        """Test basic category creation."""
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics',
            description='Electronic devices'
        )
        
        self.assertEqual(category.name, 'Electronics')
        self.assertEqual(category.store, self.store)
        self.assertEqual(category.tenant_id, 1)
    
    def test_category_unique_name_per_store(self):
        """Test that category names are unique within a store."""
        Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        # Creating duplicate name in same store should fail
        with self.assertRaises(Exception):
            Category.objects.create(
                store=self.store,
                tenant_id=self.store.tenant_id,
                name='Electronics'
            )
    
    def test_same_name_different_stores(self):
        """Test that same category name can exist in different stores."""
        store2 = Store.objects.create(
            owner=self.user,
            name='Test Store 2',
            tenant_id=2
        )
        
        cat1 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        cat2 = Category.objects.create(
            store=store2,
            tenant_id=store2.tenant_id,
            name='Electronics'
        )
        
        self.assertEqual(cat1.name, cat2.name)
        self.assertNotEqual(cat1.store, cat2.store)
    
    def test_category_tenant_id_auto_set(self):
        """Test that tenant_id is auto-set from store."""
        category = Category.objects.create(
            store=self.store,
            name='Test Category'
            # Intentionally not setting tenant_id
        )
        
        self.assertEqual(category.tenant_id, self.store.tenant_id)
    
    def test_category_str_representation(self):
        """Test category string representation."""
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        expected = f"Electronics (Store: {self.store.name})"
        self.assertEqual(str(category), expected)


class CategoryServiceTests(TestCase):
    """Test Category service layer functions."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            tenant_id=1
        )
        
        self.store = Store.objects.create(
            owner=self.user,
            name='Test Store',
            tenant_id=1
        )
    
    def test_create_category_valid(self):
        """Test creating a category with valid data."""
        category = services.create_category(
            store=self.store,
            name='Electronics',
            description='Electronic devices',
            user=self.user
        )
        
        self.assertIsNotNone(category.id)
        self.assertEqual(category.name, 'Electronics')
        self.assertEqual(category.description, 'Electronic devices')
        self.assertEqual(category.tenant_id, self.store.tenant_id)
    
    def test_create_category_empty_name(self):
        """Test that empty name raises ValidationError."""
        from django.core.exceptions import ValidationError
        
        with self.assertRaises(ValidationError):
            services.create_category(
                store=self.store,
                name='',
                user=self.user
            )
    
    def test_create_category_duplicate_name(self):
        """Test that duplicate name in store raises ValidationError."""
        from django.core.exceptions import ValidationError
        
        services.create_category(
            store=self.store,
            name='Electronics',
            user=self.user
        )
        
        with self.assertRaises(ValidationError):
            services.create_category(
                store=self.store,
                name='Electronics',
                user=self.user
            )
    
    def test_update_category_valid(self):
        """Test updating a category with valid data."""
        category = services.create_category(
            store=self.store,
            name='Electronics',
            user=self.user
        )
        
        updated = services.update_category(
            category=category,
            name='Home Appliances',
            description='Appliances for the home',
            user=self.user
        )
        
        self.assertEqual(updated.name, 'Home Appliances')
        self.assertEqual(updated.description, 'Appliances for the home')
    
    def test_update_category_empty_name(self):
        """Test that updating with empty name raises ValidationError."""
        from django.core.exceptions import ValidationError
        
        category = services.create_category(
            store=self.store,
            name='Electronics',
            user=self.user
        )
        
        with self.assertRaises(ValidationError):
            services.update_category(
                category=category,
                name='',
                user=self.user
            )
    
    def test_delete_category(self):
        """Test deleting a category."""
        category = services.create_category(
            store=self.store,
            name='Electronics',
            user=self.user
        )
        
        category_id = category.id
        
        result = services.delete_category(category, user=self.user)
        
        self.assertTrue(result)
        self.assertFalse(Category.objects.filter(id=category_id).exists())


class CategorySelectorTests(TestCase):
    """Test Category selector functions."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            tenant_id=1
        )
        
        self.store = Store.objects.create(
            owner=self.user,
            name='Test Store',
            tenant_id=1
        )
        
        self.cat1 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        self.cat2 = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Clothing'
        )
    
    def test_get_store_categories(self):
        """Test retrieving all categories for a store."""
        categories = selectors.get_store_categories(self.store)
        
        self.assertEqual(categories.count(), 2)
        self.assertIn(self.cat1, categories)
        self.assertIn(self.cat2, categories)
    
    def test_get_category_by_id(self):
        """Test retrieving a category by ID."""
        category = selectors.get_category_by_id(self.cat1.id, self.store)
        
        self.assertEqual(category.id, self.cat1.id)
        self.assertEqual(category.name, 'Electronics')
    
    def test_get_category_by_id_wrong_store(self):
        """Test that retrieving category from wrong store fails."""
        from django.core.exceptions import ObjectDoesNotExist
        
        store2 = Store.objects.create(
            owner=self.user,
            name='Test Store 2',
            tenant_id=2
        )
        
        with self.assertRaises(ObjectDoesNotExist):
            selectors.get_category_by_id(self.cat1.id, store2)
    
    def test_get_category_by_name(self):
        """Test retrieving a category by name."""
        category = selectors.get_category_by_name(self.store, 'Electronics')
        
        self.assertIsNotNone(category)
        self.assertEqual(category.name, 'Electronics')
    
    def test_get_category_by_name_nonexistent(self):
        """Test retrieving nonexistent category returns None."""
        category = selectors.get_category_by_name(self.store, 'Nonexistent')
        
        self.assertIsNone(category)


class CategoryAPITests(APITestCase):
    """Test Category API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            tenant_id=1
        )
        
        self.store = Store.objects.create(
            owner=self.user,
            name='Test Store',
            tenant_id=1
        )
        
        # Get JWT tokens
        from rest_framework_simplejwt.tokens import RefreshToken
        
        refresh = RefreshToken.for_user(self.user)
        self.access_token = str(refresh.access_token)
        
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
    
    def test_list_categories(self):
        """Test listing categories for a store."""
        Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Clothing'
        )
        
        url = f'/api/stores/{self.store.id}/categories/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
    
    def test_create_category(self):
        """Test creating a category via API."""
        url = f'/api/stores/{self.store.id}/categories/'
        data = {
            'name': 'Electronics',
            'description': 'Electronic devices'
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Electronics')
        self.assertEqual(response.data['description'], 'Electronic devices')
    
    def test_create_category_missing_name(self):
        """Test that creating category without name fails."""
        url = f'/api/stores/{self.store.id}/categories/'
        data = {'description': 'Some description'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_retrieve_category(self):
        """Test retrieving a single category."""
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        url = f'/api/stores/{self.store.id}/categories/{category.id}/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Electronics')
    
    def test_update_category(self):
        """Test updating a category via API."""
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        url = f'/api/stores/{self.store.id}/categories/{category.id}/'
        data = {
            'name': 'Home Appliances',
            'description': 'Appliances for the home'
        }
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Home Appliances')
    
    def test_delete_category(self):
        """Test deleting a category via API."""
        category = Category.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name='Electronics'
        )
        
        url = f'/api/stores/{self.store.id}/categories/{category.id}/'
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Category.objects.filter(id=category.id).exists())


class CategoryMultiTenantTests(APITestCase):
    """Test multi-tenant isolation for categories."""
    
    def setUp(self):
        """Set up test data with multiple tenants."""
        # User 1 (Tenant 1)
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123',
            tenant_id=1
        )
        
        # User 2 (Tenant 2)
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123',
            tenant_id=2
        )
        
        # Store for Tenant 1
        self.store1 = Store.objects.create(
            owner=self.user1,
            name='Store 1',
            tenant_id=1
        )
        
        # Store for Tenant 2
        self.store2 = Store.objects.create(
            owner=self.user2,
            name='Store 2',
            tenant_id=2
        )
        
        # Category in Store 1
        self.cat1 = Category.objects.create(
            store=self.store1,
            tenant_id=1,
            name='Electronics'
        )
        
        # Category in Store 2
        self.cat2 = Category.objects.create(
            store=self.store2,
            tenant_id=2,
            name='Electronics'  # Same name, different store
        )
        
        # Setup client for User 1
        from rest_framework_simplejwt.tokens import RefreshToken
        
        refresh = RefreshToken.for_user(self.user1)
        self.token1 = str(refresh.access_token)
        
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1}')
    
    def test_user1_cannot_list_store2_categories(self):
        """Test that User 1 cannot list Store 2's categories."""
        url = f'/api/stores/{self.store2.id}/categories/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_user1_cannot_retrieve_store2_category(self):
        """Test that User 1 cannot retrieve Store 2's category."""
        url = f'/api/stores/{self.store2.id}/categories/{self.cat2.id}/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_user1_cannot_create_in_store2(self):
        """Test that User 1 cannot create category in Store 2."""
        url = f'/api/stores/{self.store2.id}/categories/'
        data = {'name': 'New Category'}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_user1_cannot_update_store2_category(self):
        """Test that User 1 cannot update Store 2's category."""
        url = f'/api/stores/{self.store2.id}/categories/{self.cat2.id}/'
        data = {'name': 'Updated Name'}
        
        response = self.client.put(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_user1_cannot_delete_store2_category(self):
        """Test that User 1 cannot delete Store 2's category."""
        url = f'/api/stores/{self.store2.id}/categories/{self.cat2.id}/'
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_user1_can_list_own_store_categories(self):
        """Test that User 1 can list their own store's categories."""
        url = f'/api/stores/{self.store1.id}/categories/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Electronics')
    
    def test_tenant_isolation_in_queries(self):
        """Test that selectors properly filter by tenant_id."""
        categories = selectors.get_store_categories(self.store1)
        
        # Should only get categories from store1
        self.assertEqual(categories.count(), 1)
        self.assertEqual(categories[0].tenant_id, 1)
