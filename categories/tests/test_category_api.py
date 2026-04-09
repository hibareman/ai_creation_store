from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User
from stores.models import Store
from categories.models import Category


class CategoryApiTests(TestCase):
    """API tests for Category CRUD and tenant isolation."""

    def setUp(self):
        self.client = APIClient()

        self.user_a = User.objects.create_user(
            username='tenant_a',
            email='tenant_a@example.com',
            password='pass123'
        )
        self.user_a.is_active = True
        self.user_a.tenant_id = 1
        self.user_a.save()

        self.user_b = User.objects.create_user(
            username='tenant_b',
            email='tenant_b@example.com',
            password='pass123'
        )
        self.user_b.is_active = True
        self.user_b.tenant_id = 2
        self.user_b.save()

        self.store_a = Store.objects.create(
            owner=self.user_a,
            name='Store A',
            tenant_id=1
        )
        self.store_b = Store.objects.create(
            owner=self.user_b,
            name='Store B',
            tenant_id=2
        )

        self.category_a = Category.objects.create(
            store=self.store_a,
            tenant_id=self.store_a.tenant_id,
            name='Electronics',
            description='Electronic devices'
        )

        self.category_b = Category.objects.create(
            store=self.store_b,
            tenant_id=self.store_b.tenant_id,
            name='Books',
            description='Book products'
        )

        refresh_a = RefreshToken.for_user(self.user_a)
        self.auth_header_a = f'Bearer {str(refresh_a.access_token)}'

        refresh_b = RefreshToken.for_user(self.user_b)
        self.auth_header_b = f'Bearer {str(refresh_b.access_token)}'

    def test_list_categories_for_store(self):
        response = self.client.get(
            f'/api/stores/{self.store_a.id}/categories/',
            HTTP_AUTHORIZATION=self.auth_header_a
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Electronics')

    def test_create_category_success(self):
        payload = {
            'name': 'Clothing',
            'description': 'Apparel and fashion'
        }
        response = self.client.post(
            f'/api/stores/{self.store_a.id}/categories/',
            payload,
            HTTP_AUTHORIZATION=self.auth_header_a,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Clothing')
        self.assertTrue(Category.objects.filter(store=self.store_a, name='Clothing').exists())

    def test_create_category_duplicate_name_fails(self):
        payload = {
            'name': 'Electronics',
            'description': 'Duplicate name test'
        }
        response = self.client.post(
            f'/api/stores/{self.store_a.id}/categories/',
            payload,
            HTTP_AUTHORIZATION=self.auth_header_a,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_retrieve_category_detail(self):
        response = self.client.get(
            f'/api/stores/{self.store_a.id}/categories/{self.category_a.id}/',
            HTTP_AUTHORIZATION=self.auth_header_a
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Electronics')

    def test_update_category_success(self):
        payload = {
            'name': 'Consumer Electronics',
            'description': 'Updated description'
        }
        response = self.client.patch(
            f'/api/stores/{self.store_a.id}/categories/{self.category_a.id}/',
            payload,
            HTTP_AUTHORIZATION=self.auth_header_a,
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.category_a.refresh_from_db()
        self.assertEqual(self.category_a.name, 'Consumer Electronics')
        self.assertEqual(self.category_a.description, 'Updated description')

    def test_delete_category_success(self):
        response = self.client.delete(
            f'/api/stores/{self.store_a.id}/categories/{self.category_a.id}/',
            HTTP_AUTHORIZATION=self.auth_header_a
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Category.objects.filter(id=self.category_a.id).exists())

    def test_cross_tenant_category_access_denied(self):
        response = self.client.get(
            f'/api/stores/{self.store_b.id}/categories/',
            HTTP_AUTHORIZATION=self.auth_header_a
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        payload = {
            'name': 'Malicious',
            'description': 'Should not be created'
        }
        response = self.client.post(
            f'/api/stores/{self.store_b.id}/categories/',
            payload,
            HTTP_AUTHORIZATION=self.auth_header_a,
            format='json'
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cross_tenant_category_detail_denied(self):
        response = self.client.get(
            f'/api/stores/{self.store_b.id}/categories/{self.category_b.id}/',
            HTTP_AUTHORIZATION=self.auth_header_a
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
