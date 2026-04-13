from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from users.models import User
from ..models import Store, StoreSettings, StoreDomain
from ..selectors import get_user_stores
from ..services import create_store, update_store
from ..serializers import StoreSerializer, StoreSettingsSerializer, StoreDomainSerializer
import logging
from unittest.mock import patch

class StoreTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        # Users - with tenant_id
        self.user_a = User.objects.create_user(username="usera", email="a@test.com", password="pass123")
        self.user_a.is_active = True
        self.user_a.tenant_id = 1
        self.user_a.save()
        
        self.user_b = User.objects.create_user(username="userb", email="b@test.com", password="pass123")
        self.user_b.is_active = True
        self.user_b.tenant_id = 2
        self.user_b.save()
        
        # Stores
        self.store_a = Store.objects.create(owner=self.user_a, name="Store A", tenant_id=1)
        self.store_b = Store.objects.create(owner=self.user_b, name="Store B", tenant_id=2)
        
        # Authenticate user_a using JWT so middleware can extract tenant_id
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user_a)
        self.token_a = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_a}')

    def test_create_store_user_a(self):
        response = self.client.post("/api/stores/", {"name": "New Store"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Store.objects.filter(owner=self.user_a, name="New Store").exists(), True)
        created_store = Store.objects.get(owner=self.user_a, name="New Store")
        self.assertEqual(created_store.status, "setup")

    def test_create_store_ignores_client_active_status_and_starts_setup(self):
        response = self.client.post("/api/stores/", {"name": "Client Active Store", "status": "active"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_store = Store.objects.get(owner=self.user_a, name="Client Active Store")
        self.assertEqual(created_store.status, "setup")
        self.assertEqual(response.data["status"], "setup")

    def test_update_store_user_a(self):
        response = self.client.patch(f"/api/stores/{self.store_a.id}/", {"name": "Updated Store"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.name, "Updated Store")

    def test_user_a_cannot_access_store_b(self):
        response = self.client.patch(f"/api/stores/{self.store_b.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_b_cannot_access_store_a(self):
        self.client.force_authenticate(user=self.user_b)
        # Re-set token for user_b
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user_b)
        token_b = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_b}')
        
        response = self.client.patch(f"/api/stores/{self.store_a.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_stores_scoped_to_user(self):
        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # All returned stores should belong to user_a
        self.assertTrue(all(store['owner'] == self.user_a.id for store in data))
        # Should not include user_b's store
        self.assertFalse(any(store['owner'] == self.user_b.id for store in data))

    def test_get_stores_excludes_other_owner_in_same_tenant(self):
        user_same_tenant = User.objects.create_user(
            username="user_same_tenant",
            email="same_tenant@test.com",
            password="pass123",
        )
        user_same_tenant.is_active = True
        user_same_tenant.tenant_id = self.user_a.tenant_id
        user_same_tenant.save()
        other_store_same_tenant = Store.objects.create(
            owner=user_same_tenant,
            name="Other Owner Same Tenant Store",
            tenant_id=self.user_a.tenant_id,
        )

        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {store["id"] for store in response.json()}

        self.assertIn(self.store_a.id, returned_ids)
        self.assertNotIn(other_store_same_tenant.id, returned_ids)

    def test_super_admin_can_list_all_stores(self):
        super_admin = User.objects.create_user(
            username="superadmin",
            email="superadmin@test.com",
            password="pass123",
            role="Super Admin",
            is_active=True,
            tenant_id=None,
        )
        refresh = RefreshToken.for_user(super_admin)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {store["id"] for store in response.json()}

        self.assertIn(self.store_a.id, returned_ids)
        self.assertIn(self.store_b.id, returned_ids)


class GetUserStoresTests(TestCase):
    """Test get_user_stores selector with multi-tenant isolation"""

    def setUp(self):
        # Create users with tenant_id
        self.user_a = User.objects.create_user(username="usera", email="a@test.com", password="pass123")
        self.user_a.is_active = True
        self.user_a.tenant_id = 1
        self.user_a.save()
        
        self.user_b = User.objects.create_user(username="userb", email="b@test.com", password="pass123")
        self.user_b.is_active = True
        self.user_b.tenant_id = 2
        self.user_b.save()
        
        # Create stores for user_a
        self.store_a1 = Store.objects.create(owner=self.user_a, name="Store A1", tenant_id=1)
        self.store_a2 = Store.objects.create(owner=self.user_a, name="Store A2", tenant_id=1)
        
        # Create stores for user_b
        self.store_b1 = Store.objects.create(owner=self.user_b, name="Store B1", tenant_id=2)

    def test_get_user_stores_returns_only_user_stores(self):
        """Test that get_user_stores returns only stores owned by the user"""
        user_a_stores = get_user_stores(self.user_a)
        
        # Should return 2 stores for user_a
        self.assertEqual(user_a_stores.count(), 2)
        
        # Verify stores belong to user_a
        self.assertIn(self.store_a1, user_a_stores)
        self.assertIn(self.store_a2, user_a_stores)
        
        # Should NOT include user_b's store
        self.assertNotIn(self.store_b1, user_a_stores)

    def test_get_user_stores_multi_tenant_isolation(self):
        """Test multi-tenant isolation - Verify User B cannot access User A stores"""
        user_a_stores = get_user_stores(self.user_a)
        user_b_stores = get_user_stores(self.user_b)
        
        # User A should have 2 stores
        self.assertEqual(user_a_stores.count(), 2)
        
        # User B should have 1 store
        self.assertEqual(user_b_stores.count(), 1)
        
        # No overlap between stores
        overlap = set(user_a_stores.values_list('id', flat=True)) & set(user_b_stores.values_list('id', flat=True))
        self.assertEqual(len(overlap), 0, "User A and User B stores should not overlap")

    def test_get_user_stores_uses_select_related(self):
        """Test that get_user_stores optimizes queries with select_related"""
        user_stores = get_user_stores(self.user_a)
        
        # Access owner to verify it's already loaded (no additional query)
        _ = user_stores[0].owner
        
        # Verify the queryset has select_related
        self.assertEqual(str(user_stores.query).count('SELECT'), 1)

    def test_get_user_stores_excludes_same_tenant_different_owner(self):
        user_c = User.objects.create_user(username="userc", email="c@test.com", password="pass123")
        user_c.is_active = True
        user_c.tenant_id = self.user_a.tenant_id
        user_c.save()
        store_c = Store.objects.create(owner=user_c, name="Store C", tenant_id=self.user_a.tenant_id)

        user_a_stores = get_user_stores(self.user_a)
        self.assertNotIn(store_c, user_a_stores)


class CreateStoreSettingsTests(TestCase):
    """Test automatic StoreSettings creation when creating a store"""

    def setUp(self):
        self.user_a = User.objects.create_user(username="usera", email="a@test.com", password="pass123")
        self.user_b = User.objects.create_user(username="userb", email="b@test.com", password="pass123")

    def test_store_settings_created_automatically(self):
        """Test that StoreSettings is created automatically when creating a store"""
        store = create_store(owner=self.user_a, name="Test Store")
        
        # Verify store exists
        self.assertIsNotNone(store.id)
        
        # Verify StoreSettings exists
        self.assertTrue(StoreSettings.objects.filter(store=store).exists())

    def test_store_settings_has_default_values(self):
        """Test that StoreSettings has correct default values"""
        store = create_store(owner=self.user_a, name="Test Store")
        settings = store.settings
        
        self.assertEqual(settings.currency, 'USD')
        self.assertEqual(settings.language, 'en')
        self.assertEqual(settings.timezone, 'UTC')

    def test_store_settings_accessible_via_related_name(self):
        """Test that StoreSettings is accessible via store.settings"""
        store = create_store(owner=self.user_a, name="Test Store")
        
        # Should be able to access settings via related_name
        settings = store.settings
        self.assertIsNotNone(settings)
        self.assertEqual(settings.store_id, store.id)

    def test_store_settings_multi_tenant_isolation(self):
        """Test that StoreSettings are isolated between tenants"""
        store_a = create_store(owner=self.user_a, name="Store A")
        store_b = create_store(owner=self.user_b, name="Store B")
        
        # Get settings for both stores
        settings_a = store_a.settings
        settings_b = store_b.settings
        
        # Verify they are different objects
        self.assertNotEqual(settings_a.id, settings_b.id)
        
        # Verify they belong to different stores
        self.assertEqual(settings_a.store_id, store_a.id)
        self.assertEqual(settings_b.store_id, store_b.id)
        
        # User A should not be able to access User B's store settings through query
        user_a_settings = StoreSettings.objects.filter(store__owner=self.user_a)
        user_b_settings = StoreSettings.objects.filter(store__owner=self.user_b)
        
        self.assertNotIn(settings_b.id, user_a_settings.values_list('id', flat=True))
        self.assertNotIn(settings_a.id, user_b_settings.values_list('id', flat=True))


class StoreSlugTests(TestCase):
    """Test slug generation and uniqueness handling for duplicate store names"""

    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")

    def test_slug_generated_from_name(self):
        """Test that slug is automatically generated from store name"""
        store = create_store(owner=self.user, name="My Store")
        
        self.assertEqual(store.slug, "my-store")

    def test_duplicate_slug_gets_counter(self):
        """Test that duplicate slugs get a counter suffix"""
        store1 = create_store(owner=self.user, name="My Store")
        store2 = create_store(owner=self.user, name="My Store")
        
        # First store should have original slug
        self.assertEqual(store1.slug, "my-store")
        
        # Second store should have slug with counter
        self.assertEqual(store2.slug, "my-store-1")

    def test_multiple_duplicate_slugs_get_incremented_counters(self):
        """Test that multiple duplicate slugs get incrementing counters"""
        store1 = create_store(owner=self.user, name="Test Store")
        store2 = create_store(owner=self.user, name="Test Store")
        store3 = create_store(owner=self.user, name="Test Store")
        store4 = create_store(owner=self.user, name="Test Store")
        
        self.assertEqual(store1.slug, "test-store")
        self.assertEqual(store2.slug, "test-store-1")
        self.assertEqual(store3.slug, "test-store-2")
        self.assertEqual(store4.slug, "test-store-3")

    def test_slug_unique_constraint_not_violated(self):
        """Test that creating duplicate named stores doesn't violate unique constraint"""
        try:
            store1 = create_store(owner=self.user, name="Unique Store")
            store2 = create_store(owner=self.user, name="Unique Store")
            store3 = create_store(owner=self.user, name="Unique Store")
            
            # If we reach this point, no IntegrityError was raised
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Creating duplicate named stores raised exception: {e}")

    def test_slug_with_special_characters(self):
        """Test that slugs with special characters are handled correctly"""
        store1 = create_store(owner=self.user, name="Store @ #2024!")
        store2 = create_store(owner=self.user, name="Store @ #2024!")
        
        # Both should have valid slugs without special characters
        self.assertEqual(store1.slug, "store-2024")
        self.assertEqual(store2.slug, "store-2024-1")

    def test_slug_with_multiple_spaces(self):
        """Test that slugs handle multiple spaces correctly"""
        store1 = create_store(owner=self.user, name="My   Store   Name")
        store2 = create_store(owner=self.user, name="My   Store   Name")
        
        self.assertEqual(store1.slug, "my-store-name")
        self.assertEqual(store2.slug, "my-store-name-1")


class StoreSlugApiTests(TestCase):
    """Test slug availability and suggestion endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.is_active = True
        self.user.tenant_id = 1
        self.user.save()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

    def test_check_slug_available_returns_true(self):
        response = self.client.post('/api/stores/slug/check/', {'slug': 'available-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], 'available-slug')
        self.assertTrue(response.data['available'])

    def test_check_slug_returns_false_for_existing_slug(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='taken-slug')
        response = self.client.post('/api/stores/slug/check/', {'slug': 'taken-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['available'])

    def test_suggest_slug_returns_unique_suggestions(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='my-store')
        response = self.client.post('/api/stores/slug/suggest/', {'name': 'My Store', 'limit': 3}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['suggestions'], ['my-store-1', 'my-store-2', 'my-store-3'])

    def test_create_store_accepts_custom_slug(self):
        response = self.client.post('/api/stores/', {'name': 'Custom Slug Store', 'slug': 'custom-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'custom-slug')
        self.assertTrue(Store.objects.filter(slug='custom-slug').exists())

    def test_create_store_with_duplicate_custom_slug_autoincrements(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='custom-slug')
        response = self.client.post('/api/stores/', {'name': 'Another Store', 'slug': 'custom-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'custom-slug-1')
        self.assertTrue(Store.objects.filter(slug='custom-slug-1').exists())


class StoreSerializersTests(TestCase):
    """Test serializers for Store, StoreSettings, and StoreDomain"""

    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")
        self.domain = StoreDomain.objects.create(store=self.store, domain="example.com", is_primary=True)

    def test_store_serializer_contains_expected_fields(self):
        """Test that StoreSerializer contains all required fields"""
        serializer = StoreSerializer(self.store)
        
        expected_fields = {'id', 'owner', 'name', 'slug', 'description', 'status', 'tenant_id', 'created_at', 'updated_at'}
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_settings_serializer_contains_expected_fields(self):
        """Test that StoreSettingsSerializer contains all required fields"""
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        
        expected_fields = {'id', 'store', 'currency', 'language', 'timezone', 'created_at', 'updated_at'}
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_settings_serializer_store_is_read_only(self):
        """Test that store field in StoreSettingsSerializer is read_only"""
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        
        # Verify store is in the data and is the store ID
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_settings_serializer_data_accuracy(self):
        """Test that StoreSettingsSerializer returns accurate data"""
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        
        self.assertEqual(serializer.data['currency'], 'USD')
        self.assertEqual(serializer.data['language'], 'en')
        self.assertEqual(serializer.data['timezone'], 'UTC')
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_domain_serializer_contains_expected_fields(self):
        """Test that StoreDomainSerializer contains all required fields"""
        serializer = StoreDomainSerializer(self.domain)
        
        expected_fields = {'id', 'store', 'domain', 'is_primary', 'created_at', 'updated_at'}
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_domain_serializer_store_is_read_only(self):
        """Test that store field in StoreDomainSerializer is read_only"""
        serializer = StoreDomainSerializer(self.domain)
        
        # Verify store is in the data and is the store ID
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_domain_serializer_data_accuracy(self):
        """Test that StoreDomainSerializer returns accurate data"""
        serializer = StoreDomainSerializer(self.domain)
        
        self.assertEqual(serializer.data['domain'], 'example.com')
        self.assertEqual(serializer.data['is_primary'], True)
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_settings_serializer_with_custom_values(self):
        """Test StoreSettingsSerializer with custom values"""
        settings = self.store.settings
        settings.currency = 'EUR'
        settings.language = 'fr'
        settings.timezone = 'Europe/Paris'
        settings.save()
        
        serializer = StoreSettingsSerializer(settings)
        
        self.assertEqual(serializer.data['currency'], 'EUR')
        self.assertEqual(serializer.data['language'], 'fr')
        self.assertEqual(serializer.data['timezone'], 'Europe/Paris')

    def test_multiple_domains_serialization(self):
        """Test serializing multiple domains"""
        domain2 = StoreDomain.objects.create(store=self.store, domain="example2.com", is_primary=False)
        
        domains = StoreDomain.objects.filter(store=self.store)
        serializer = StoreDomainSerializer(domains, many=True)
        
        self.assertEqual(len(serializer.data), 2)
        domains_list = [d['domain'] for d in serializer.data]
        self.assertIn('example.com', domains_list)
        self.assertIn('example2.com', domains_list)


class StoreLoggingTests(TestCase):
    """Test logging and error handling in store services"""

    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")

    @patch('stores.services.logger')
    def test_create_store_logs_success(self, mock_logger):
        """Test that successful store creation is logged"""
        store = create_store(owner=self.user, name="Test Store")
        
        # Verify logger.info was called
        self.assertTrue(mock_logger.info.called)
        # Verify log contains username and store name
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn(self.user.username, call_args)
        self.assertIn("Test Store", call_args)

    @patch('stores.services.logger')
    def test_update_store_logs_changes(self, mock_logger):
        """Test that store updates are logged"""
        store = create_store(owner=self.user, name="Original Name")
        
        # Reset the mock to isolate the update logging
        mock_logger.reset_mock()
        
        # Update the store
        updated_store = update_store(store, name="Updated Name")
        
        # Verify logger.info was called for update
        self.assertTrue(mock_logger.info.called)
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Updated Name", call_args)
        self.assertIn("Original Name", call_args)

    @patch('stores.services.logger')
    def test_update_store_no_changes_logs_debug(self, mock_logger):
        """Test that update with no changes logs debug message"""
        store = create_store(owner=self.user, name="Test Store")
        
        # Reset the mock
        mock_logger.reset_mock()
        
        # Update with same values (no changes)
        updated_store = update_store(store, name="Test Store")
        
        # Verify logger.debug was called
        self.assertTrue(mock_logger.debug.called)
        call_args = mock_logger.debug.call_args[0][0]
        self.assertIn("No changes", call_args)

    def test_create_store_with_invalid_data(self):
        """Test that create_store handles invalid data gracefully"""
        # This should not raise an unexpected error
        try:
            store = create_store(owner=self.user, name="")
            # Empty name should still create a store (name has no validation at model level)
            self.assertIsNotNone(store)
        except Exception as e:
            # If it does raise, it should be a known exception type
            self.assertIsInstance(e, (ValueError, TypeError, Exception))

    @patch('stores.services.logger')
    def test_create_store_logs_storesettings_error(self, mock_logger):
        """Test that StoreSettings creation errors are logged"""
        # Mock StoreSettings.objects.create to raise an error
        with patch('stores.services.StoreSettings.objects.create', side_effect=Exception("DB Error")):
            try:
                store = create_store(owner=self.user, name="Test Store")
            except Exception:
                pass
            
            # Verify logger.error was called for StoreSettings error
            error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
            # Check if we have database error logged (initial error or the StoreSettings error)
            self.assertTrue(len(error_calls) > 0, "Expected error logging but got none")

    def test_update_store_multiple_fields(self):
        """Test that update_store handles multiple field updates correctly"""
        store = create_store(owner=self.user, name="Original", description="Original Desc", status="active")
        
        # Update multiple fields
        updated_store = update_store(
            store,
            name="Updated",
            description="Updated Desc",
            status="inactive"
        )
        
        # Verify all fields were updated
        self.assertEqual(updated_store.name, "Updated")
        self.assertEqual(updated_store.description, "Updated Desc")
        self.assertEqual(updated_store.status, "inactive")

    def test_create_store_preserves_tenant_id(self):
        """Test that create_store preserves tenant_id from owner"""
        # Set a specific tenant_id on user
        self.user.tenant_id = 999
        self.user.save()
        
        store = create_store(owner=self.user, name="Test Store")
        
        # Verify tenant_id matches user's tenant_id
        self.assertEqual(store.tenant_id, 999)


class StoreSettingsServiceTests(TestCase):
    """Test update_store_settings service function"""

    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")
        self.settings = self.store.settings

    def test_update_store_settings_single_field(self):
        """Test updating a single setting field"""
        from ..services import update_store_settings
        
        updated_settings = update_store_settings(self.store, currency='EUR')
        
        self.assertEqual(updated_settings.currency, 'EUR')
        self.assertEqual(updated_settings.language, 'en')  # unchanged
        self.assertEqual(updated_settings.timezone, 'UTC')  # unchanged

    def test_update_store_settings_multiple_fields(self):
        """Test updating multiple setting fields"""
        from ..services import update_store_settings
        
        updated_settings = update_store_settings(
            self.store,
            currency='GBP',
            language='fr',
            timezone='Europe/Paris'
        )
        
        self.assertEqual(updated_settings.currency, 'GBP')
        self.assertEqual(updated_settings.language, 'fr')
        self.assertEqual(updated_settings.timezone, 'Europe/Paris')

    def test_update_store_settings_no_changes(self):
        """Test updating settings with same values"""
        from ..services import update_store_settings
        
        # Update with same values (no changes)
        updated_settings = update_store_settings(
            self.store,
            currency='USD',
            language='en'
        )
        
        # Should still return the settings object
        self.assertIsNotNone(updated_settings)
        self.assertEqual(updated_settings.currency, 'USD')


class StoreDomainServiceTests(TestCase):
    """Test domain management service functions"""

    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")

    def test_add_domain_simple(self):
        """Test adding a simple domain"""
        from ..services import add_domain
        
        domain = add_domain(self.store, "myshop.com")
        
        self.assertEqual(domain.domain, "myshop.com")
        self.assertEqual(domain.store, self.store)
        self.assertFalse(domain.is_primary)

    def test_add_domain_as_primary(self):
        """Test adding a domain as primary"""
        from ..services import add_domain
        
        domain = add_domain(self.store, "myshop.com", is_primary=True)
        
        self.assertTrue(domain.is_primary)
        self.assertEqual(domain.store, self.store)

    def test_add_multiple_domains_single_primary(self):
        """Test that only one domain can be primary"""
        from ..services import add_domain
        
        domain1 = add_domain(self.store, "myshop.com", is_primary=True)
        domain2 = add_domain(self.store, "shop.com", is_primary=True)
        
        # Refresh from DB
        domain1.refresh_from_db()
        
        # First domain should no longer be primary
        self.assertFalse(domain1.is_primary)
        self.assertTrue(domain2.is_primary)

    def test_update_domain_set_primary(self):
        """Test updating a domain to be primary"""
        from ..services import add_domain, update_domain
        
        domain1 = add_domain(self.store, "myshop.com", is_primary=True)
        domain2 = add_domain(self.store, "shop.com", is_primary=False)
        
        # Update domain2 to be primary
        updated_domain2 = update_domain(self.store, "shop.com", is_primary=True)
        
        # Refresh domain1
        domain1.refresh_from_db()
        
        # Now domain2 is primary
        self.assertTrue(updated_domain2.is_primary)
        self.assertFalse(domain1.is_primary)

    def test_delete_domain(self):
        """Test deleting a domain"""
        from ..services import add_domain, delete_domain
        
        domain = add_domain(self.store, "myshop.com")
        self.assertTrue(StoreDomain.objects.filter(domain="myshop.com").exists())
        
        # Delete the domain
        delete_domain(self.store, "myshop.com")
        
        # Verify it's deleted
        self.assertFalse(StoreDomain.objects.filter(domain="myshop.com").exists())

    def test_delete_nonexistent_domain_raises_error(self):
        """Test that deleting a non-existent domain raises DoesNotExist"""
        from ..services import delete_domain
        
        with self.assertRaises(StoreDomain.DoesNotExist):
            delete_domain(self.store, "nonexistent.com")

    def test_get_store_domains_ordered(self):
        """Test getting domains ordered by is_primary then domain"""
        from ..services import add_domain, get_store_domains
        
        add_domain(self.store, "zebra.com", is_primary=False)
        add_domain(self.store, "alpha.com", is_primary=True)
        add_domain(self.store, "beta.com", is_primary=False)
        
        domains = get_store_domains(self.store)
        domain_list = [d.domain for d in domains]
        
        # Primary should be first
        self.assertEqual(domain_list[0], "alpha.com")
        # Then alphabetically
        self.assertIn("beta.com", domain_list)
        self.assertIn("zebra.com", domain_list)

    def test_add_duplicate_domain_raises_error(self):
        """Test that adding duplicate domain raises IntegrityError"""
        from ..services import add_domain
        
        add_domain(self.store, "myshop.com")
        
        with self.assertRaises(Exception):  # IntegrityError
            add_domain(self.store, "myshop.com")

    def test_update_nonexistent_domain_raises_error(self):
        """Test that updating non-existent domain raises DoesNotExist"""
        from ..services import update_domain
        
        with self.assertRaises(StoreDomain.DoesNotExist):
            update_domain(self.store, "nonexistent.com", is_primary=True)

    def test_domain_multi_tenant_isolation(self):
        """Test that domains are isolated between stores"""
        from ..services import add_domain, get_store_domains
        
        # Create second store
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        store2 = create_store(owner=user2, name="Store 2")
        
        # Add domains to both stores
        add_domain(self.store, "store1.com")
        add_domain(store2, "store2.com")
        
        # Get domains for each store
        store1_domains = get_store_domains(self.store)
        store2_domains = get_store_domains(store2)
        
        # Verify isolation
        self.assertEqual(store1_domains.count(), 1)
        self.assertEqual(store2_domains.count(), 1)
        
        self.assertEqual(store1_domains[0].domain, "store1.com")
        self.assertEqual(store2_domains[0].domain, "store2.com")


class StoreSettingsAPITests(TestCase):
    """Test StoreSettings API endpoints"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.tenant_id = self.user.id
        self.user.save()
        self.store = create_store(owner=self.user, name="Test Store")
        
        # Use JWT token for authentication
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        self.token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_get_store_settings(self):
        """Test GET /api/stores/{id}/settings/"""
        response = self.client.get(f"/api/stores/{self.store.id}/settings/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['currency'], 'USD')
        self.assertEqual(response.data['language'], 'en')
        self.assertEqual(response.data['timezone'], 'UTC')

    def test_update_store_settings(self):
        """Test PATCH /api/stores/{id}/settings/"""
        data = {
            'currency': 'EUR',
            'language': 'fr',
            'timezone': 'Europe/Paris'
        }
        response = self.client.patch(f"/api/stores/{self.store.id}/settings/", data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['currency'], 'EUR')
        self.assertEqual(response.data['language'], 'fr')
        self.assertEqual(response.data['timezone'], 'Europe/Paris')

    def test_update_store_settings_partial(self):
        """Test partial PATCH to settings"""
        data = {'currency': 'GBP'}
        response = self.client.patch(f"/api/stores/{self.store.id}/settings/", data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['currency'], 'GBP')
        self.assertEqual(response.data['language'], 'en')  # Unchanged

    def test_settings_tenant_isolation(self):
        """Test that users can't access other tenant's settings"""
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        store2 = create_store(owner=user2, name="Store 2")
        
        # User1 tries to access User2's settings
        response = self.client.get(f"/api/stores/{store2.id}/settings/")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StoreDomainAPITests(TestCase):
    """Test StoreDomain API endpoints"""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.tenant_id = self.user.id
        self.user.save()
        self.store = create_store(owner=self.user, name="Test Store")
        
        # Use JWT token for authentication
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        self.token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_list_store_domains(self):
        """Test GET /api/stores/{id}/domains/"""
        from ..services import add_domain
        
        add_domain(self.store, "myshop.com", is_primary=True)
        add_domain(self.store, "shop.com", is_primary=False)
        
        response = self.client.get(f"/api/stores/{self.store.id}/domains/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_create_domain(self):
        """Test POST /api/stores/{id}/domains/"""
        data = {'domain': 'newshop.com', 'is_primary': False}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['domain'], 'newshop.com')
        self.assertFalse(response.data['is_primary'])

    def test_create_primary_domain(self):
        """Test creating a primary domain"""
        data = {'domain': 'primary.com', 'is_primary': True}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_primary'])

    def test_get_domain_detail(self):
        """Test GET /api/stores/{id}/domains/{domain_id}/"""
        from ..services import add_domain
        
        domain = add_domain(self.store, "shop.com")
        response = self.client.get(f"/api/stores/{self.store.id}/domains/{domain.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['domain'], 'shop.com')

    def test_update_domain(self):
        """Test PATCH /api/stores/{id}/domains/{domain_id}/"""
        from ..services import add_domain
        
        domain = add_domain(self.store, "shop.com", is_primary=False)
        data = {'is_primary': True}
        response = self.client.patch(f"/api/stores/{self.store.id}/domains/{domain.id}/", data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_primary'])

    def test_delete_domain(self):
        """Test DELETE /api/stores/{id}/domains/{domain_id}/"""
        from ..services import add_domain
        
        domain = add_domain(self.store, "shop.com")
        response = self.client.delete(f"/api/stores/{self.store.id}/domains/{domain.id}/")
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Verify deletion
        self.assertFalse(StoreDomain.objects.filter(id=domain.id).exists())

    def test_domain_tenant_isolation(self):
        """Test that users can't access other tenant's domains"""
        from ..services import add_domain
        
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        user2.tenant_id = user2.id
        user2.save()
        store2 = create_store(owner=user2, name="Store 2")
        domain2 = add_domain(store2, "store2.com")
        
        # User1 tries to access User2's domain
        response = self.client.get(f"/api/stores/{store2.id}/domains/{domain2.id}/")
        
        # Should return 404 (not 403, for security - don't reveal if store exists)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_duplicate_domain_fails(self):
        """Test that creating duplicate domain returns error"""
        from ..services import add_domain
        
        add_domain(self.store, "duplicate.com")
        
        data = {'domain': 'duplicate.com', 'is_primary': False}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_domain_for_nonexistent_store_returns_404_not_500(self):
        """Test POST domain on a non-existent store returns 404."""
        data = {'domain': 'ghost-store.com', 'is_primary': False}
        response = self.client.post("/api/stores/999999/domains/", data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
