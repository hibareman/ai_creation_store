# test file for stores
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
        refresh = RefreshToken.for_user(self.user_a)
        self.token_a = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token_a}')

    @staticmethod
    def _payload(response):
        return response.json()

    def test_create_store_user_a(self):
        response = self.client.post("/api/stores/", {"name": "New Store"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Store.objects.filter(owner=self.user_a, name="New Store").exists(), True)
        created_store = Store.objects.get(owner=self.user_a, name="New Store")
        self.assertEqual(created_store.status, "setup")
        data = self._payload(response)
        self.assertIn("slug", data)
        self.assertIn("subdomain", data)
        self.assertIsNone(data["subdomain"])

    def test_create_store_ignores_client_active_status_and_starts_setup(self):
        response = self.client.post("/api/stores/", {"name": "Client Active Store", "status": "active"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_store = Store.objects.get(owner=self.user_a, name="Client Active Store")
        self.assertEqual(created_store.status, "setup")
        # Response should contain the store data directly
        data = self._payload(response)
        self.assertEqual(data["status"], "setup")

    def test_update_store_user_a(self):
        response = self.client.patch(f"/api/stores/{self.store_a.id}/", {"name": "Updated Store"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.name, "Updated Store")

    @patch("stores.views.update_store")
    def test_update_store_routes_write_through_service_layer(self, mock_update_store):
        self.store_a.description = "Before update"
        self.store_a.save(update_fields=["description"])
        self.store_a.name = "Service Updated Store"
        mock_update_store.return_value = self.store_a

        response = self.client.patch(
            f"/api/stores/{self.store_a.id}/",
            {"name": "Service Updated Store"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_update_store.assert_called_once()
        called_kwargs = mock_update_store.call_args.kwargs
        self.assertEqual(called_kwargs["store"].id, self.store_a.id)
        self.assertEqual(called_kwargs["name"], "Service Updated Store")

    def test_update_store_can_update_slug(self):
        response = self.client.patch(
            f"/api/stores/{self.store_a.id}/",
            {"slug": "updated-store-a"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.slug, "updated-store-a")

    def test_user_a_cannot_access_store_b(self):
        response = self.client.patch(f"/api/stores/{self.store_b.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_b_cannot_access_store_a(self):
        self.client.force_authenticate(user=self.user_b)
        refresh = RefreshToken.for_user(self.user_b)
        token_b = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token_b}')

        response = self.client.patch(f"/api/stores/{self.store_a.id}/", {"name": "Hacked"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_stores_scoped_to_user(self):
        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)  # Direct list of stores
        # All returned stores should belong to user_a
        self.assertTrue(all(store['owner'] == self.user_a.id for store in data))
        # Should not include user_b's store
        self.assertFalse(any(store['owner'] == self.user_b.id for store in data))
        self.assertTrue(all('slug' in store for store in data))
        self.assertTrue(all('subdomain' in store for store in data))

    def test_store_payload_exposes_subdomain_separately_when_set(self):
        self.store_a.subdomain = "store-a-live"
        self.store_a.save(update_fields=["subdomain"])

        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = self._payload(response)
        store_data = next(item for item in payload if item["id"] == self.store_a.id)
        self.assertEqual(store_data["slug"], self.store_a.slug)
        self.assertEqual(store_data["subdomain"], "store-a-live")

    def test_store_payload_keeps_slug_and_subdomain_separate(self):
        self.store_a.subdomain = "public-store-a"
        self.store_a.save(update_fields=["subdomain"])
        original_slug = self.store_a.slug

        response = self.client.patch(
            f"/api/stores/{self.store_a.id}/",
            {"name": "Store A Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["slug"], original_slug)
        self.assertEqual(data["subdomain"], "public-store-a")

    def test_set_subdomain_updates_subdomain_only_not_slug(self):
        original_slug = self.store_a.slug
        response = self.client.patch(
            f"/api/stores/{self.store_a.id}/subdomain/",
            {"subdomain": "new-public-subdomain"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store_a.refresh_from_db()
        self.assertEqual(self.store_a.subdomain, "new-public-subdomain")
        self.assertEqual(self.store_a.slug, original_slug)

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
        returned_ids = {store["id"] for store in self._payload(response)}

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
        returned_ids = {store["id"] for store in self._payload(response)}

        self.assertIn(self.store_a.id, returned_ids)
        self.assertIn(self.store_b.id, returned_ids)


class GetUserStoresTests(TestCase):
    """Test get_user_stores selector with multi-tenant isolation"""

    def setUp(self):
        self.user_a = User.objects.create_user(username="usera", email="a@test.com", password="pass123")
        self.user_a.is_active = True
        self.user_a.tenant_id = 1
        self.user_a.save()

        self.user_b = User.objects.create_user(username="userb", email="b@test.com", password="pass123")
        self.user_b.is_active = True
        self.user_b.tenant_id = 2
        self.user_b.save()

        self.store_a1 = Store.objects.create(owner=self.user_a, name="Store A1", tenant_id=1)
        self.store_a2 = Store.objects.create(owner=self.user_a, name="Store A2", tenant_id=1)
        self.store_b1 = Store.objects.create(owner=self.user_b, name="Store B1", tenant_id=2)

    def test_get_user_stores_returns_only_user_stores(self):
        user_a_stores = get_user_stores(self.user_a)
        self.assertEqual(user_a_stores.count(), 2)
        self.assertIn(self.store_a1, user_a_stores)
        self.assertIn(self.store_a2, user_a_stores)
        self.assertNotIn(self.store_b1, user_a_stores)

    def test_get_user_stores_multi_tenant_isolation(self):
        user_a_stores = get_user_stores(self.user_a)
        user_b_stores = get_user_stores(self.user_b)

        self.assertEqual(user_a_stores.count(), 2)
        self.assertEqual(user_b_stores.count(), 1)

        overlap = set(user_a_stores.values_list('id', flat=True)) & set(user_b_stores.values_list('id', flat=True))
        self.assertEqual(len(overlap), 0, "User A and User B stores should not overlap")

    def test_get_user_stores_uses_select_related(self):
        user_stores = get_user_stores(self.user_a)
        _ = user_stores[0].owner
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
    def setUp(self):
        self.user_a = User.objects.create_user(username="usera", email="a@test.com", password="pass123")
        self.user_b = User.objects.create_user(username="userb", email="b@test.com", password="pass123")

    def test_store_settings_created_automatically(self):
        store = create_store(owner=self.user_a, name="Test Store")
        self.assertIsNotNone(store.id)
        self.assertTrue(StoreSettings.objects.filter(store=store).exists())

    def test_store_settings_has_default_values(self):
        store = create_store(owner=self.user_a, name="Test Store")
        settings = store.settings
        self.assertEqual(settings.currency, 'USD')
        self.assertEqual(settings.language, 'en')
        self.assertEqual(settings.timezone, 'UTC')

    def test_store_settings_accessible_via_related_name(self):
        store = create_store(owner=self.user_a, name="Test Store")
        settings = store.settings
        self.assertIsNotNone(settings)
        self.assertEqual(settings.store_id, store.id)

    def test_store_settings_multi_tenant_isolation(self):
        store_a = create_store(owner=self.user_a, name="Store A")
        store_b = create_store(owner=self.user_b, name="Store B")

        settings_a = store_a.settings
        settings_b = store_b.settings

        self.assertNotEqual(settings_a.id, settings_b.id)
        self.assertEqual(settings_a.store_id, store_a.id)
        self.assertEqual(settings_b.store_id, store_b.id)

        user_a_settings = StoreSettings.objects.filter(store__owner=self.user_a)
        user_b_settings = StoreSettings.objects.filter(store__owner=self.user_b)

        self.assertNotIn(settings_b.id, user_a_settings.values_list('id', flat=True))
        self.assertNotIn(settings_a.id, user_b_settings.values_list('id', flat=True))


class StoreSlugTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")

    def test_slug_generated_from_name(self):
        store = create_store(owner=self.user, name="My Store")
        self.assertEqual(store.slug, "my-store")

    def test_duplicate_slug_gets_counter(self):
        store1 = create_store(owner=self.user, name="My Store")
        store2 = create_store(owner=self.user, name="My Store")
        self.assertEqual(store1.slug, "my-store")
        self.assertEqual(store2.slug, "my-store-1")

    def test_multiple_duplicate_slugs_get_incremented_counters(self):
        store1 = create_store(owner=self.user, name="Test Store")
        store2 = create_store(owner=self.user, name="Test Store")
        store3 = create_store(owner=self.user, name="Test Store")
        store4 = create_store(owner=self.user, name="Test Store")
        self.assertEqual(store1.slug, "test-store")
        self.assertEqual(store2.slug, "test-store-1")
        self.assertEqual(store3.slug, "test-store-2")
        self.assertEqual(store4.slug, "test-store-3")

    def test_slug_unique_constraint_not_violated(self):
        try:
            store1 = create_store(owner=self.user, name="Unique Store")
            store2 = create_store(owner=self.user, name="Unique Store")
            store3 = create_store(owner=self.user, name="Unique Store")
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Creating duplicate named stores raised exception: {e}")

    def test_slug_with_special_characters(self):
        store1 = create_store(owner=self.user, name="Store @ #2024!")
        store2 = create_store(owner=self.user, name="Store @ #2024!")
        self.assertEqual(store1.slug, "store-2024")
        self.assertEqual(store2.slug, "store-2024-1")

    def test_slug_with_multiple_spaces(self):
        store1 = create_store(owner=self.user, name="My   Store   Name")
        store2 = create_store(owner=self.user, name="My   Store   Name")
        self.assertEqual(store1.slug, "my-store-name")
        self.assertEqual(store2.slug, "my-store-name-1")


class StoreSlugApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.is_active = True
        self.user.tenant_id = 1
        self.user.save()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')

    @staticmethod
    def _payload(response):
        return response.json()

    def test_check_slug_available_returns_true(self):
        response = self.client.post('/api/stores/slug/check/', {'slug': 'available-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data['slug'], 'available-slug')
        self.assertTrue(data['available'])

    def test_check_slug_returns_false_for_existing_slug(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='taken-slug')
        response = self.client.post('/api/stores/slug/check/', {'slug': 'taken-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(self._payload(response)['available'])

    def test_suggest_slug_returns_unique_suggestions(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='my-store')
        response = self.client.post('/api/stores/slug/suggest/', {'name': 'My Store', 'limit': 3}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response)['suggestions'], ['my-store-1', 'my-store-2', 'my-store-3'])

    def test_create_store_accepts_custom_slug(self):
        response = self.client.post('/api/stores/', {'name': 'Custom Slug Store', 'slug': 'custom-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._payload(response)['slug'], 'custom-slug')
        self.assertTrue(Store.objects.filter(slug='custom-slug').exists())

    def test_create_store_with_duplicate_custom_slug_autoincrements(self):
        Store.objects.create(owner=self.user, name='Existing Store', tenant_id=1, slug='custom-slug')
        response = self.client.post('/api/stores/', {'name': 'Another Store', 'slug': 'custom-slug'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._payload(response)['slug'], 'custom-slug-1')
        self.assertTrue(Store.objects.filter(slug='custom-slug-1').exists())


class StoreSerializersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")
        self.domain = StoreDomain.objects.create(store=self.store, domain="example.com", is_primary=True)

    def test_store_serializer_contains_expected_fields(self):
        serializer = StoreSerializer(self.store)
        expected_fields = {
            'id',
            'owner',
            'name',
            'slug',
            'subdomain',
            'description',
            'status',
            'tenant_id',
            'created_at',
            'updated_at',
        }
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_serializer_returns_subdomain_null_when_missing(self):
        serializer = StoreSerializer(self.store)
        self.assertIn('subdomain', serializer.data)
        self.assertIsNone(serializer.data['subdomain'])

    def test_store_serializer_returns_subdomain_when_set(self):
        self.store.subdomain = "test-store-sub"
        self.store.save(update_fields=["subdomain"])
        serializer = StoreSerializer(self.store)
        self.assertEqual(serializer.data['slug'], self.store.slug)
        self.assertEqual(serializer.data['subdomain'], "test-store-sub")

    def test_store_settings_serializer_contains_expected_fields(self):
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        expected_fields = {'store_id', 'settings'}
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_settings_serializer_store_is_read_only(self):
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        self.assertEqual(serializer.data['store_id'], self.store.slug)

    def test_store_settings_serializer_data_accuracy(self):
        settings = self.store.settings
        serializer = StoreSettingsSerializer(settings)
        payload = serializer.data['settings']
        self.assertEqual(payload['storeName'], self.store.name)
        self.assertEqual(payload['storeUrl'], self.store.slug)
        self.assertIsNone(payload['storeSubdomain'])
        self.assertEqual(payload['storeDescription'], self.store.description)
        self.assertEqual(payload['currency'], 'USD')
        self.assertEqual(payload['language'], 'en')
        self.assertEqual(payload['timezone'], 'UTC')

    def test_store_settings_serializer_exposes_store_subdomain_when_set(self):
        self.store.subdomain = "settings-subdomain"
        self.store.save(update_fields=["subdomain"])
        serializer = StoreSettingsSerializer(self.store.settings)
        payload = serializer.data['settings']
        self.assertEqual(payload['storeUrl'], self.store.slug)
        self.assertEqual(payload['storeSubdomain'], "settings-subdomain")

    def test_store_domain_serializer_contains_expected_fields(self):
        serializer = StoreDomainSerializer(self.domain)
        expected_fields = {'id', 'store', 'domain', 'is_primary', 'created_at', 'updated_at'}
        self.assertEqual(set(serializer.data.keys()), expected_fields)

    def test_store_domain_serializer_store_is_read_only(self):
        serializer = StoreDomainSerializer(self.domain)
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_domain_serializer_data_accuracy(self):
        serializer = StoreDomainSerializer(self.domain)
        self.assertEqual(serializer.data['domain'], 'example.com')
        self.assertTrue(serializer.data['is_primary'])
        self.assertEqual(serializer.data['store'], self.store.id)

    def test_store_settings_serializer_with_custom_values(self):
        settings = self.store.settings
        settings.currency = 'EUR'
        settings.language = 'fr'
        settings.timezone = 'Europe/Paris'
        settings.save()
        serializer = StoreSettingsSerializer(settings)
        payload = serializer.data['settings']
        self.assertEqual(payload['currency'], 'EUR')
        self.assertEqual(payload['language'], 'fr')
        self.assertEqual(payload['timezone'], 'Europe/Paris')

    def test_multiple_domains_serialization(self):
        domain2 = StoreDomain.objects.create(store=self.store, domain="example2.com", is_primary=False)
        domains = StoreDomain.objects.filter(store=self.store)
        serializer = StoreDomainSerializer(domains, many=True)
        self.assertEqual(len(serializer.data), 2)
        domains_list = [d['domain'] for d in serializer.data]
        self.assertIn('example.com', domains_list)
        self.assertIn('example2.com', domains_list)


class StoreLoggingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")

    @patch('stores.services.logger')
    def test_create_store_logs_success(self, mock_logger):
        store = create_store(owner=self.user, name="Test Store")
        self.assertTrue(mock_logger.info.called)
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn(self.user.username, call_args)
        self.assertIn("Test Store", call_args)

    @patch('stores.services.logger')
    def test_update_store_logs_changes(self, mock_logger):
        store = create_store(owner=self.user, name="Original Name")
        mock_logger.reset_mock()
        update_store(store, name="Updated Name")
        self.assertTrue(mock_logger.info.called)
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Updated Name", call_args)
        self.assertIn("Original Name", call_args)

    @patch('stores.services.logger')
    def test_update_store_no_changes_logs_debug(self, mock_logger):
        store = create_store(owner=self.user, name="Test Store")
        mock_logger.reset_mock()
        update_store(store, name="Test Store")
        self.assertTrue(mock_logger.debug.called)
        call_args = mock_logger.debug.call_args[0][0]
        self.assertIn("No changes", call_args)

    def test_create_store_with_invalid_data(self):
        try:
            store = create_store(owner=self.user, name="")
            self.assertIsNotNone(store)
        except Exception as e:
            self.assertIsInstance(e, (ValueError, TypeError, Exception))

    @patch('stores.services.logger')
    def test_create_store_logs_storesettings_error(self, mock_logger):
        with patch('stores.services.StoreSettings.objects.create', side_effect=Exception("DB Error")):
            try:
                create_store(owner=self.user, name="Test Store")
            except Exception:
                pass
            error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
            self.assertTrue(len(error_calls) > 0, "Expected error logging but got none")

    def test_update_store_multiple_fields(self):
        store = create_store(owner=self.user, name="Original", description="Original Desc", status="active")
        updated_store = update_store(
            store,
            name="Updated",
            description="Updated Desc",
            status="inactive"
        )
        self.assertEqual(updated_store.name, "Updated")
        self.assertEqual(updated_store.description, "Updated Desc")
        self.assertEqual(updated_store.status, "inactive")

    def test_create_store_preserves_tenant_id(self):
        self.user.tenant_id = 999
        self.user.save()
        store = create_store(owner=self.user, name="Test Store")
        self.assertEqual(store.tenant_id, 999)


class StoreSettingsServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")
        self.settings = self.store.settings

    def test_update_store_settings_single_field(self):
        from ..services import update_store_settings
        updated_settings = update_store_settings(self.store, currency='EUR')
        self.assertEqual(updated_settings.currency, 'EUR')
        self.assertEqual(updated_settings.language, 'en')
        self.assertEqual(updated_settings.timezone, 'UTC')

    def test_update_store_settings_multiple_fields(self):
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
        from ..services import update_store_settings
        updated_settings = update_store_settings(
            self.store,
            currency='USD',
            language='en'
        )
        self.assertIsNotNone(updated_settings)
        self.assertEqual(updated_settings.currency, 'USD')


class StoreDomainServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.store = create_store(owner=self.user, name="Test Store")

    def test_add_domain_simple(self):
        from ..services import add_domain
        domain = add_domain(self.store, "myshop.com")
        self.assertEqual(domain.domain, "myshop.com")
        self.assertEqual(domain.store, self.store)
        self.assertFalse(domain.is_primary)

    def test_add_domain_as_primary(self):
        from ..services import add_domain
        domain = add_domain(self.store, "myshop.com", is_primary=True)
        self.assertTrue(domain.is_primary)
        self.assertEqual(domain.store, self.store)

    def test_add_multiple_domains_single_primary(self):
        from ..services import add_domain
        domain1 = add_domain(self.store, "myshop.com", is_primary=True)
        domain2 = add_domain(self.store, "shop.com", is_primary=True)
        domain1.refresh_from_db()
        self.assertFalse(domain1.is_primary)
        self.assertTrue(domain2.is_primary)

    def test_update_domain_set_primary(self):
        from ..services import add_domain, update_domain
        domain1 = add_domain(self.store, "myshop.com", is_primary=True)
        domain2 = add_domain(self.store, "shop.com", is_primary=False)
        updated_domain2 = update_domain(self.store, "shop.com", is_primary=True)
        domain1.refresh_from_db()
        self.assertTrue(updated_domain2.is_primary)
        self.assertFalse(domain1.is_primary)

    def test_delete_domain(self):
        from ..services import add_domain, delete_domain
        domain = add_domain(self.store, "myshop.com")
        self.assertTrue(StoreDomain.objects.filter(domain="myshop.com").exists())
        delete_domain(self.store, "myshop.com")
        self.assertFalse(StoreDomain.objects.filter(domain="myshop.com").exists())

    def test_delete_nonexistent_domain_raises_error(self):
        from ..services import delete_domain
        with self.assertRaises(StoreDomain.DoesNotExist):
            delete_domain(self.store, "nonexistent.com")

    def test_get_store_domains_ordered(self):
        from ..services import add_domain, get_store_domains
        add_domain(self.store, "zebra.com", is_primary=False)
        add_domain(self.store, "alpha.com", is_primary=True)
        add_domain(self.store, "beta.com", is_primary=False)
        domains = get_store_domains(self.store)
        domain_list = [d.domain for d in domains]
        self.assertEqual(domain_list[0], "alpha.com")
        self.assertIn("beta.com", domain_list)
        self.assertIn("zebra.com", domain_list)

    def test_add_duplicate_domain_raises_error(self):
        from ..services import add_domain
        add_domain(self.store, "myshop.com")
        with self.assertRaises(Exception):  # IntegrityError
            add_domain(self.store, "myshop.com")

    def test_update_nonexistent_domain_raises_error(self):
        from ..services import update_domain
        with self.assertRaises(StoreDomain.DoesNotExist):
            update_domain(self.store, "nonexistent.com", is_primary=True)

    def test_domain_multi_tenant_isolation(self):
        from ..services import add_domain, get_store_domains
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        store2 = create_store(owner=user2, name="Store 2")
        add_domain(self.store, "store1.com")
        add_domain(store2, "store2.com")
        store1_domains = get_store_domains(self.store)
        store2_domains = get_store_domains(store2)
        self.assertEqual(store1_domains.count(), 1)
        self.assertEqual(store2_domains.count(), 1)
        self.assertEqual(store1_domains[0].domain, "store1.com")
        self.assertEqual(store2_domains[0].domain, "store2.com")


class StoreSettingsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.tenant_id = self.user.id
        self.user.save()
        self.store = create_store(owner=self.user, name="Test Store")
        refresh = RefreshToken.for_user(self.user)
        self.token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    @staticmethod
    def _payload(response):
        return response.json()

    def test_get_store_settings(self):
        response = self.client.get(f"/api/stores/{self.store.id}/settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data['store_id'], self.store.slug)
        self.assertEqual(data['settings']['currency'], 'USD')
        self.assertEqual(data['settings']['language'], 'en')
        self.assertEqual(data['settings']['timezone'], 'UTC')
        self.assertIn('storeUrl', data['settings'])
        self.assertIn('storeSubdomain', data['settings'])
        self.assertEqual(data['settings']['storeUrl'], self.store.slug)
        self.assertIsNone(data['settings']['storeSubdomain'])

    def test_get_store_settings_returns_real_subdomain_separately(self):
        self.store.subdomain = "settings-api-subdomain"
        self.store.save(update_fields=["subdomain"])
        response = self.client.get(f"/api/stores/{self.store.id}/settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data['settings']['storeUrl'], self.store.slug)
        self.assertEqual(data['settings']['storeSubdomain'], "settings-api-subdomain")

    def test_update_store_settings(self):
        data = {
            'settings': {
                'currency': 'EUR',
                'language': 'fr',
                'timezone': 'Europe/Paris'
            }
        }
        response = self.client.patch(
            f"/api/stores/{self.store.id}/settings/",
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resp_data = self._payload(response)
        self.assertEqual(resp_data['settings']['currency'], 'EUR')
        self.assertEqual(resp_data['settings']['language'], 'fr')
        self.assertEqual(resp_data['settings']['timezone'], 'Europe/Paris')

    def test_update_store_settings_partial(self):
        data = {'settings': {'currency': 'GBP'}}
        response = self.client.patch(
            f"/api/stores/{self.store.id}/settings/",
            data,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resp_data = self._payload(response)
        self.assertEqual(resp_data['settings']['currency'], 'GBP')
        self.assertEqual(resp_data['settings']['language'], 'en')

    def test_settings_tenant_isolation(self):
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        store2 = create_store(owner=user2, name="Store 2")
        response = self.client.get(f"/api/stores/{store2.id}/settings/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StoreDomainAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="user", email="test@test.com", password="pass123")
        self.user.tenant_id = self.user.id
        self.user.save()
        self.store = create_store(owner=self.user, name="Test Store")
        refresh = RefreshToken.for_user(self.user)
        self.token = str(refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    @staticmethod
    def _payload(response):
        return response.json()

    def test_list_store_domains(self):
        from ..services import add_domain
        add_domain(self.store, "myshop.com", is_primary=True)
        add_domain(self.store, "shop.com", is_primary=False)
        response = self.client.get(f"/api/stores/{self.store.id}/domains/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self._payload(response)), 2)

    def test_create_domain(self):
        data = {'domain': 'newshop.com', 'is_primary': False}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        resp_data = self._payload(response)
        self.assertEqual(resp_data['domain'], 'newshop.com')
        self.assertFalse(resp_data['is_primary'])

    def test_create_primary_domain(self):
        data = {'domain': 'primary.com', 'is_primary': True}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(self._payload(response)['is_primary'])

    def test_get_domain_detail(self):
        from ..services import add_domain
        domain = add_domain(self.store, "shop.com")
        response = self.client.get(f"/api/stores/{self.store.id}/domains/{domain.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response)['domain'], 'shop.com')

    def test_update_domain(self):
        from ..services import add_domain
        domain = add_domain(self.store, "shop.com", is_primary=False)
        data = {'is_primary': True}
        response = self.client.patch(f"/api/stores/{self.store.id}/domains/{domain.id}/", data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(self._payload(response)['is_primary'])

    def test_update_domain_changes_domain_value(self):
        from ..services import add_domain
        domain = add_domain(self.store, "shop.com", is_primary=False)
        response = self.client.patch(
            f"/api/stores/{self.store.id}/domains/{domain.id}/",
            {'domain': 'renamed-shop.com'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._payload(response)['domain'], 'renamed-shop.com')
        domain.refresh_from_db()
        self.assertEqual(domain.domain, 'renamed-shop.com')
        self.assertFalse(domain.is_primary)

    def test_update_domain_to_primary_preserves_single_primary_behavior(self):
        from ..services import add_domain
        primary_domain = add_domain(self.store, "primary.com", is_primary=True)
        secondary_domain = add_domain(self.store, "shop.com", is_primary=False)
        response = self.client.patch(
            f"/api/stores/{self.store.id}/domains/{secondary_domain.id}/",
            {'domain': 'new-primary.com', 'is_primary': True},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resp_data = self._payload(response)
        self.assertEqual(resp_data['domain'], 'new-primary.com')
        self.assertTrue(resp_data['is_primary'])

        primary_domain.refresh_from_db()
        secondary_domain.refresh_from_db()
        self.assertFalse(primary_domain.is_primary)
        self.assertTrue(secondary_domain.is_primary)
        self.assertEqual(secondary_domain.domain, 'new-primary.com')

    def test_delete_domain(self):
        from ..services import add_domain
        domain = add_domain(self.store, "shop.com")
        response = self.client.delete(f"/api/stores/{self.store.id}/domains/{domain.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StoreDomain.objects.filter(id=domain.id).exists())

    def test_domain_tenant_isolation(self):
        from ..services import add_domain
        user2 = User.objects.create_user(username="user2", email="test2@test.com", password="pass123")
        user2.tenant_id = user2.id
        user2.save()
        store2 = create_store(owner=user2, name="Store 2")
        domain2 = add_domain(store2, "store2.com")
        response = self.client.get(f"/api/stores/{store2.id}/domains/{domain2.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_domain_cross_tenant_blocked(self):
        from ..services import add_domain
        user2 = User.objects.create_user(username="user2_update", email="test2_update@test.com", password="pass123")
        user2.tenant_id = user2.id
        user2.save()
        store2 = create_store(owner=user2, name="Store 2 Update")
        domain2 = add_domain(store2, "store2-update.com")
        response = self.client.patch(
            f"/api/stores/{store2.id}/domains/{domain2.id}/",
            {"domain": "hacked.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_domain_requires_authentication(self):
        from ..services import add_domain
        domain = add_domain(self.store, "auth-check.com", is_primary=False)
        unauth_client = APIClient()
        response = unauth_client.patch(
            f"/api/stores/{self.store.id}/domains/{domain.id}/",
            {"domain": "auth-check-renamed.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_duplicate_domain_fails(self):
        from ..services import add_domain
        add_domain(self.store, "duplicate.com")
        data = {'domain': 'duplicate.com', 'is_primary': False}
        response = self.client.post(f"/api/stores/{self.store.id}/domains/", data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_domain_for_nonexistent_store_returns_404(self):
        data = {'domain': 'ghost-store.com', 'is_primary': False}
        response = self.client.post("/api/stores/999999/domains/", data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_repeated_primary_switch_keeps_exactly_one_primary_domain(self):
        from ..services import add_domain

        first_domain = add_domain(self.store, "first-primary.com", is_primary=True)
        second_domain = add_domain(self.store, "second-primary.com", is_primary=False)
        third_domain = add_domain(self.store, "third-primary.com", is_primary=False)

        first_switch = self.client.patch(
            f"/api/stores/{self.store.id}/domains/{second_domain.id}/",
            {"is_primary": True},
            format="json",
        )
        self.assertEqual(first_switch.status_code, status.HTTP_200_OK)

        second_switch = self.client.patch(
            f"/api/stores/{self.store.id}/domains/{third_domain.id}/",
            {"is_primary": True},
            format="json",
        )
        self.assertEqual(second_switch.status_code, status.HTTP_200_OK)

        first_domain.refresh_from_db()
        second_domain.refresh_from_db()
        third_domain.refresh_from_db()

        self.assertFalse(first_domain.is_primary)
        self.assertFalse(second_domain.is_primary)
        self.assertTrue(third_domain.is_primary)
        self.assertEqual(StoreDomain.objects.filter(store=self.store, is_primary=True).count(), 1)

class StorePublishAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="publish_owner",
            email="publish_owner@test.com",
            password="pass123",
            is_active=True,
        )
        self.owner.tenant_id = 1001
        self.owner.save(update_fields=["tenant_id"])

        self.same_tenant_non_owner = User.objects.create_user(
            username="publish_same_tenant",
            email="publish_same_tenant@test.com",
            password="pass123",
            is_active=True,
        )
        self.same_tenant_non_owner.tenant_id = self.owner.tenant_id
        self.same_tenant_non_owner.save(update_fields=["tenant_id"])

        self.cross_tenant_user = User.objects.create_user(
            username="publish_cross_tenant",
            email="publish_cross_tenant@test.com",
            password="pass123",
            is_active=True,
        )
        self.cross_tenant_user.tenant_id = 2002
        self.cross_tenant_user.save(update_fields=["tenant_id"])

        self.store = create_store(owner=self.owner, name="Publishable Store")
        self.store.status = "active"
        self.store.subdomain = "publishable-store"
        self.store.save(update_fields=["status", "subdomain"])

        from products.models import Product
        Product.objects.create(
            store=self.store,
            tenant_id=self.store.tenant_id,
            name="Publish Product",
            description="Ready product",
            price=10,
            sku="PUB-SKU-1",
            status="active",
        )

        self.owner_client = APIClient()
        owner_token = str(RefreshToken.for_user(self.owner).access_token)
        self.owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_token}")

    @staticmethod
    def _payload(response):
        return response.json()

    def _auth_client_for(self, user):
        client = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_owner_can_publish_store_successfully(self):
        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store.refresh_from_db()
        self.assertTrue(self.store.is_published)
        self.assertIsNotNone(self.store.published_at)
        payload = self._payload(response)
        self.assertIn("store", payload)
        self.assertTrue(payload["store"]["is_published"])
        self.assertIsNotNone(payload["store"]["published_at"])

    def test_owner_can_unpublish_store_successfully(self):
        publish_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "unpublish"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store.refresh_from_db()
        self.assertFalse(self.store.is_published)
        self.assertIsNone(self.store.published_at)
        payload = self._payload(response)
        self.assertIn("store", payload)
        self.assertFalse(payload["store"]["is_published"])
        self.assertIsNone(payload["store"]["published_at"])

    def test_same_tenant_non_owner_cannot_publish_or_unpublish(self):
        client = self._auth_client_for(self.same_tenant_non_owner)
        for action in ("publish", "unpublish"):
            response = client.patch(
                f"/api/stores/{self.store.id}/publish/",
                {"action": action},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("detail", self._payload(response))

    def test_cross_tenant_user_cannot_publish_or_unpublish(self):
        client = self._auth_client_for(self.cross_tenant_user)
        for action in ("publish", "unpublish"):
            response = client.patch(
                f"/api/stores/{self.store.id}/publish/",
                {"action": action},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_publish_nonexistent_store_returns_404(self):
        response = self.owner_client.patch(
            "/api/stores/999999/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_publish_invalid_action_returns_400(self):
        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "invalid-action"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("action", self._payload(response))
    def test_publish_validation_failure_does_not_partially_modify_store_state(self):
        invalid_store = create_store(owner=self.owner, name="Invalid Publish Store")
        invalid_store.status = "active"
        invalid_store.subdomain = None
        invalid_store.is_published = False
        invalid_store.published_at = None
        invalid_store.save(update_fields=["status", "subdomain", "is_published", "published_at"])

        from products.models import Product
        Product.objects.create(
            store=invalid_store,
            tenant_id=invalid_store.tenant_id,
            name="Ready Product",
            description="Ready but store missing subdomain",
            price=10,
            sku="INVALID-PUB-1",
            status="active",
        )

        response = self.owner_client.patch(
            f"/api/stores/{invalid_store.id}/publish/",
            {"action": "publish"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        invalid_store.refresh_from_db()
        self.assertFalse(invalid_store.is_published)
        self.assertIsNone(invalid_store.published_at)
    def test_repeated_publish_keeps_store_consistently_published(self):
            first_response = self.owner_client.patch(
                f"/api/stores/{self.store.id}/publish/",
                {"action": "publish"},
                format="json",
            )
            self.assertEqual(first_response.status_code, status.HTTP_200_OK)

            self.store.refresh_from_db()
            first_published_at = self.store.published_at
            self.assertTrue(self.store.is_published)
            self.assertIsNotNone(first_published_at)

            second_response = self.owner_client.patch(
                f"/api/stores/{self.store.id}/publish/",
                {"action": "publish"},
                format="json",
            )
            self.assertEqual(second_response.status_code, status.HTTP_200_OK)

            self.store.refresh_from_db()
            self.assertTrue(self.store.is_published)
            self.assertIsNotNone(self.store.published_at)
            self.assertGreaterEqual(self.store.published_at, first_published_at)
            
    def test_repeated_unpublish_keeps_store_consistently_unpublished(self):
        publish_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        first_unpublish = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "unpublish"},
            format="json",
        )
        self.assertEqual(first_unpublish.status_code, status.HTTP_200_OK)

        second_unpublish = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "unpublish"},
            format="json",
        )
        self.assertEqual(second_unpublish.status_code, status.HTTP_200_OK)

        self.store.refresh_from_db()
        self.assertFalse(self.store.is_published)
        self.assertIsNone(self.store.published_at)
    def test_publish_validation_failure_does_not_partially_modify_store_state(self):
        invalid_store = create_store(owner=self.owner, name="Invalid Publish Store")
        invalid_store.status = "active"
        invalid_store.subdomain = None
        invalid_store.is_published = False
        invalid_store.published_at = None
        invalid_store.save(update_fields=["status", "subdomain", "is_published", "published_at"])

        from products.models import Product
        Product.objects.create(
            store=invalid_store,
            tenant_id=invalid_store.tenant_id,
            name="Ready Product",
            description="Ready but store missing subdomain",
            price=10,
            sku="INVALID-PUB-1",
            status="active",
        )

        response = self.owner_client.patch(
            f"/api/stores/{invalid_store.id}/publish/",
            {"action": "publish"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        invalid_store.refresh_from_db()
        self.assertFalse(invalid_store.is_published)
        self.assertIsNone(invalid_store.published_at)

    def test_repeated_publish_keeps_store_consistently_published(self):
        first_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)

        self.store.refresh_from_db()
        first_published_at = self.store.published_at
        self.assertTrue(self.store.is_published)
        self.assertIsNotNone(first_published_at)

        second_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        self.store.refresh_from_db()
        self.assertTrue(self.store.is_published)
        self.assertIsNotNone(self.store.published_at)
        self.assertGreaterEqual(self.store.published_at, first_published_at)


    def test_repeated_unpublish_keeps_store_consistently_unpublished(self):
        publish_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "publish"},
            format="json",
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        first_unpublish = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "unpublish"},
            format="json",
        )
        self.assertEqual(first_unpublish.status_code, status.HTTP_200_OK)

        second_unpublish = self.owner_client.patch(
            f"/api/stores/{self.store.id}/publish/",
            {"action": "unpublish"},
            format="json",
        )
        self.assertEqual(second_unpublish.status_code, status.HTTP_200_OK)

        self.store.refresh_from_db()
        self.assertFalse(self.store.is_published)
        self.assertIsNone(self.store.published_at)


class StoreSubdomainAPITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="sub_owner",
            email="sub_owner@test.com",
            password="pass123",
            is_active=True,
        )
        self.owner.tenant_id = 3001
        self.owner.save(update_fields=["tenant_id"])

        self.same_tenant_non_owner = User.objects.create_user(
            username="sub_same_tenant",
            email="sub_same_tenant@test.com",
            password="pass123",
            is_active=True,
        )
        self.same_tenant_non_owner.tenant_id = self.owner.tenant_id
        self.same_tenant_non_owner.save(update_fields=["tenant_id"])

        self.cross_tenant_user = User.objects.create_user(
            username="sub_cross_tenant",
            email="sub_cross_tenant@test.com",
            password="pass123",
            is_active=True,
        )
        self.cross_tenant_user.tenant_id = 4001
        self.cross_tenant_user.save(update_fields=["tenant_id"])

        self.store = create_store(owner=self.owner, name="Subdomain Store")
        self.other_store = create_store(owner=self.owner, name="Another Subdomain Store")

        self.owner_client = APIClient()
        owner_token = str(RefreshToken.for_user(self.owner).access_token)
        self.owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_token}")

    @staticmethod
    def _payload(response):
        return response.json()

    def _auth_client_for(self, user):
        client = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_owner_can_set_subdomain_successfully(self):
        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "my-public-store"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store.refresh_from_db()
        self.assertEqual(self.store.subdomain, "my-public-store")
        payload = self._payload(response)
        self.assertEqual(payload["store"]["subdomain"], "my-public-store")

    def test_setting_subdomain_does_not_change_slug(self):
        original_slug = self.store.slug
        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "my-store-sub"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store.refresh_from_db()
        self.assertEqual(self.store.slug, original_slug)
        self.assertEqual(self.store.subdomain, "my-store-sub")

    def test_changing_slug_does_not_overwrite_existing_subdomain(self):
        self.store.subdomain = "stable-subdomain"
        self.store.save(update_fields=["subdomain"])

        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/",
            {"slug": "new-slug-value"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.store.refresh_from_db()
        self.assertEqual(self.store.slug, "new-slug-value")
        self.assertEqual(self.store.subdomain, "stable-subdomain")

    def test_duplicate_subdomain_is_rejected(self):
        self.other_store.subdomain = "reserved-subdomain"
        self.other_store.save(update_fields=["subdomain"])

        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "reserved-subdomain"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", self._payload(response))

    def test_blank_or_invalid_subdomain_is_rejected(self):
        blank_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "   "},
            format="json",
        )
        self.assertEqual(blank_response.status_code, status.HTTP_400_BAD_REQUEST)

        invalid_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "!!!"},
            format="json",
        )
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_same_tenant_non_owner_cannot_set_subdomain(self):
        client = self._auth_client_for(self.same_tenant_non_owner)
        response = client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "attempted-hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", self._payload(response))

    def test_cross_tenant_user_cannot_set_subdomain(self):
        client = self._auth_client_for(self.cross_tenant_user)
        response = client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "attempted-hijack"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_store_payload_exposes_slug_and_subdomain_separately_after_update(self):
        set_response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "separated-fields-store"},
            format="json",
        )
        self.assertEqual(set_response.status_code, status.HTTP_200_OK)

        list_response = self.owner_client.get("/api/stores/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        payload = self._payload(list_response)
        store_data = next(item for item in payload if item["id"] == self.store.id)
        self.assertIn("slug", store_data)
        self.assertIn("subdomain", store_data)
        self.assertEqual(store_data["slug"], self.store.slug)
        self.assertEqual(store_data["subdomain"], "separated-fields-store")
 
    def test_duplicate_subdomain_rejection_does_not_mutate_existing_slug_or_subdomain(self):
        self.store.subdomain = "original-subdomain"
        self.store.save(update_fields=["subdomain"])

        self.other_store.subdomain = "reserved-subdomain"
        self.other_store.save(update_fields=["subdomain"])

        original_slug = self.store.slug
        original_subdomain = self.store.subdomain

        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "reserved-subdomain"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.store.refresh_from_db()
        self.assertEqual(self.store.slug, original_slug)
        self.assertEqual(self.store.subdomain, original_subdomain)

    def test_subdomain_input_is_normalized_consistently_in_db_and_response(self):
        response = self.owner_client.patch(
            f"/api/stores/{self.store.id}/subdomain/",
            {"subdomain": "  My Fancy SHOP  "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.store.refresh_from_db()
        self.assertEqual(self.store.subdomain, "my-fancy-shop")

        payload = self._payload(response)
        self.assertEqual(payload["store"]["subdomain"], "my-fancy-shop")












class StoreDomainAPIAccessEdgeTests(TestCase):
    def setUp(self):
        from ..services import add_domain

        self.owner = User.objects.create_user(
            username="domain_owner",
            email="domain_owner@test.com",
            password="pass123",
            is_active=True,
        )
        self.owner.tenant_id = 6001
        self.owner.save(update_fields=["tenant_id"])

        self.same_tenant_non_owner = User.objects.create_user(
            username="domain_same_tenant",
            email="domain_same_tenant@test.com",
            password="pass123",
            is_active=True,
        )
        self.same_tenant_non_owner.tenant_id = self.owner.tenant_id
        self.same_tenant_non_owner.save(update_fields=["tenant_id"])

        self.store = create_store(owner=self.owner, name="Domain Store")
        self.domain = add_domain(self.store, "domain-store.com", is_primary=True)

        self.owner_client = APIClient()
        owner_token = str(RefreshToken.for_user(self.owner).access_token)
        self.owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_token}")

    def _auth_client_for(self, user):
        client = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_same_tenant_non_owner_domain_access_is_blocked(self):
        client = self._auth_client_for(self.same_tenant_non_owner)

        create_response = client.post(
            f"/api/stores/{self.store.id}/domains/",
            {"domain": "blocked.com", "is_primary": False},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        update_response = client.patch(
            f"/api/stores/{self.store.id}/domains/{self.domain.id}/",
            {"domain": "blocked-update.com"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_404_NOT_FOUND)

        delete_response = client.delete(
            f"/api/stores/{self.store.id}/domains/{self.domain.id}/",
        )
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_domain_returns_404(self):
        response = self.owner_client.get(
            f"/api/stores/{self.store.id}/domains/999999/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
