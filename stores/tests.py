from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User
from .models import Store, StoreDomain, StoreSettings
from rest_framework_simplejwt.tokens import RefreshToken


class CrossTenantIsolationTests(TestCase):
    """Critical tests to verify multi-tenant isolation within stores app"""

    def setUp(self):
        self.client = APIClient()
        
        # Create two different tenants with their users
        self.tenant1_user = User.objects.create_user(
            username='tenant1_user',
            email='tenant1@example.com',
            password='pass123'
        )
        self.tenant1_user.is_active = True
        self.tenant1_user.tenant_id = 1
        self.tenant1_user.save()
        
        self.tenant2_user = User.objects.create_user(
            username='tenant2_user',
            email='tenant2@example.com',
            password='pass123'
        )
        self.tenant2_user.is_active = True
        self.tenant2_user.tenant_id = 2
        self.tenant2_user.save()
        
        # Create stores for each tenant
        self.tenant1_store = Store.objects.create(
            owner=self.tenant1_user,
            name='Tenant1 Store',
            tenant_id=1
        )
        
        self.tenant2_store = Store.objects.create(
            owner=self.tenant2_user,
            name='Tenant2 Store',
            tenant_id=2
        )

    def _get_auth_header(self, user):
        """Helper to get JWT auth header for a user"""
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_tenant1_cannot_access_tenant2_store_settings(self):
        """Critical: Tenant1 user should NOT be able to access Tenant2's store settings"""
        auth = self._get_auth_header(self.tenant1_user)
        
        # Try to access Tenant2's store settings
        response = self.client.get(
            f'/api/stores/{self.tenant2_store.id}/settings/',
            HTTP_AUTHORIZATION=auth
        )
        
        # Should be denied (403 or 404)
        self.assertIn(response.status_code, [403, 404])

    def test_tenant2_cannot_access_tenant1_store_settings(self):
        """Critical: Tenant2 user should NOT be able to access Tenant1's store settings"""
        auth = self._get_auth_header(self.tenant2_user)
        
        # Try to access Tenant1's store settings
        response = self.client.get(
            f'/api/stores/{self.tenant1_store.id}/settings/',
            HTTP_AUTHORIZATION=auth
        )
        
        # Should be denied (403 or 404)
        self.assertIn(response.status_code, [403, 404])

    def test_tenant1_cannot_access_tenant2_domains(self):
        """Critical: Tenant1 user should NOT be able to list Tenant2's domains"""
        auth = self._get_auth_header(self.tenant1_user)
        
        # Add a domain to Tenant2 store
        StoreDomain.objects.create(
            store=self.tenant2_store,
            domain='tenant2.com',
            is_primary=True
        )
        
        # Try to access Tenant2's domains
        response = self.client.get(
            f'/api/stores/{self.tenant2_store.id}/domains/',
            HTTP_AUTHORIZATION=auth
        )
        
        # Should return empty or 403
        if response.status_code == 200:
            self.assertEqual(len(response.data), 0)
        else:
            self.assertIn(response.status_code, [403, 404])

    def test_tenant1_cannot_add_domain_to_tenant2_store(self):
        """Critical: Tenant1 user should NOT be able to add domains to Tenant2's store"""
        auth = self._get_auth_header(self.tenant1_user)
        
        data = {
            'domain': 'malicious.com',
            'is_primary': False
        }
        
        # Try to add domain to Tenant2's store
        response = self.client.post(
            f'/api/stores/{self.tenant2_store.id}/domains/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )
        
        # Should be denied (403 or 404)
        self.assertIn(response.status_code, [403, 404])

    def test_tenant1_can_only_see_own_stores(self):
        """Tenant1 user should only see their own stores in list"""
        auth = self._get_auth_header(self.tenant1_user)
        
        response = self.client.get(
            '/api/stores/',
            HTTP_AUTHORIZATION=auth
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Should only see Tenant1's store, not Tenant2's
        store_ids = [store['id'] for store in response.data]
        self.assertIn(self.tenant1_store.id, store_ids)
        self.assertNotIn(self.tenant2_store.id, store_ids)

    def test_tenant2_can_only_see_own_stores(self):
        """Tenant2 user should only see their own stores in list"""
        auth = self._get_auth_header(self.tenant2_user)
        
        response = self.client.get(
            '/api/stores/',
            HTTP_AUTHORIZATION=auth
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Should only see Tenant2's store, not Tenant1's
        store_ids = [store['id'] for store in response.data]
        self.assertIn(self.tenant2_store.id, store_ids)
        self.assertNotIn(self.tenant1_store.id, store_ids)

    def test_tenant1_cannot_update_tenant2_store(self):
        """Critical: Tenant1 user should NOT be able to update Tenant2's store"""
        auth = self._get_auth_header(self.tenant1_user)
        
        data = {
            'name': 'Hacked Store Name',
            'description': 'Hacked'
        }
        
        response = self.client.patch(
            f'/api/stores/{self.tenant1_store.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )
        
        self.assertIn(response.status_code, [200, 201])
        
        # Now try to update Tenant2's store
        response = self.client.patch(
            f'/api/stores/{self.tenant2_store.id}/',
            data,
            HTTP_AUTHORIZATION=auth,
            format='json'
        )
        
        # Should be denied (403 or 404)
        self.assertIn(response.status_code, [403, 404])
        
        # Verify store was NOT updated
        self.tenant2_store.refresh_from_db()
        self.assertNotEqual(self.tenant2_store.name, 'Hacked Store Name')

    def test_tenant1_cannot_delete_tenant2_store(self):
        """Critical: Tenant1 user should NOT be able to delete Tenant2's store"""
        auth = self._get_auth_header(self.tenant1_user)
        
        response = self.client.delete(
            f'/api/stores/{self.tenant2_store.id}/delete/',
            HTTP_AUTHORIZATION=auth
        )
        
        # Should be denied (403 or 404)
        self.assertIn(response.status_code, [403, 404])
        
        # Verify store was NOT deleted
        self.assertTrue(Store.objects.filter(id=self.tenant2_store.id).exists())
