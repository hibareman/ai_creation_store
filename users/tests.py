"""
Tests for JWT Authentication and Tenant Middleware
"""

from django.test import TestCase
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class RegistrationTests(TestCase):
    """Tests for user registration and email verification"""

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.activate_url = reverse('activate')
        self.login_url = reverse('login')

    def test_register_creates_inactive_user_and_sends_email(self):
        """Test that registration creates an inactive user and sends activation email"""
        data = {
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'TestPass123',
            'role': 'Store Owner'
        }

        response = self.client.post(self.register_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['detail'], 'Activation email sent.')

        # Verify user was created but is inactive
        user = User.objects.get(email='test@example.com')
        self.assertFalse(user.is_active)
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.role, 'Store Owner')

        # Verify activation email was sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Activate your account', mail.outbox[0].subject)
        self.assertIn('test@example.com', mail.outbox[0].to)

    def test_register_duplicate_email_fails(self):
        """Test that registering with existing email fails"""
        # Create user first
        User.objects.create_user(
            username='existing',
            email='existing@example.com',
            password='Pass123'
        )

        data = {
            'username': 'newuser',
            'email': 'existing@example.com',
            'password': 'TestPass123'
        }

        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ActivationTests(TestCase):
    """Tests for account activation"""

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.activate_url = reverse('activate')
        self.login_url = reverse('login')

    def test_activate_valid_token_activates_user_and_returns_tokens(self):
        """Test that valid activation token activates user and returns JWT tokens"""
        # Register user
        register_data = {
            'username': 'activateuser',
            'email': 'activate@example.com',
            'password': 'TestPass123'
        }
        self.client.post(self.register_url, register_data)

        # Get the activation token from the email
        email_body = mail.outbox[0].body
        # Extract token from URL (format: /users/activate/?token=...)
        import re
        match = re.search(r'token=([^&\s]+)', email_body)
        self.assertIsNotNone(match, "Activation token not found in email")
        token = match.group(1)

        # Activate the user
        response = self.client.get(f'{self.activate_url}?token={token}')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['role'], 'Store Owner')
        self.assertIsNotNone(response.data['tenant_id'])

        # Verify user is now active
        user = User.objects.get(email='activate@example.com')
        self.assertTrue(user.is_active)

    def test_activate_invalid_token_fails(self):
        """Test that invalid activation token returns error"""
        response = self.client.get(f'{self.activate_url}?token=invalid_token_123')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_activate_missing_token_fails(self):
        """Test that missing token parameter returns error"""
        response = self.client.get(self.activate_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing token.')


class LoginTests(TestCase):
    """Tests for login functionality"""

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.activate_url = reverse('activate')
        self.login_url = reverse('login')

    def create_and_activate_user(self, email, password):
        """Helper to create and activate a user"""
        register_data = {
            'username': email.split('@')[0],
            'email': email,
            'password': password
        }
        self.client.post(self.register_url, register_data)

        # Extract token from email
        import re
        match = re.search(r'token=([^&\s]+)', mail.outbox[0].body)
        token = match.group(1)
        self.client.get(f'{self.activate_url}?token={token}')
        mail.outbox.clear()  # Clear email box for next tests

    def test_login_with_active_user_succeeds(self):
        """Test that active user can login successfully"""
        self.create_and_activate_user('active@example.com', 'TestPass123')

        response = self.client.post(self.login_url, {
            'email': 'active@example.com',
            'password': 'TestPass123'
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['role'], 'Store Owner')
        self.assertIsNotNone(response.data['tenant_id'])

    def test_login_with_inactive_user_fails(self):
        """Test that inactive user cannot login"""
        # Register but don't activate
        register_data = {
            'username': 'inactiveuser',
            'email': 'inactive@example.com',
            'password': 'TestPass123'
        }
        self.client.post(self.register_url, register_data)
        mail.outbox.clear()

        response = self.client.post(self.login_url, {
            'email': 'inactive@example.com',
            'password': 'TestPass123'
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Email not verified.')

    def test_login_with_invalid_credentials_fails(self):
        """Test that login with wrong password fails"""
        self.create_and_activate_user('valid@example.com', 'CorrectPass123')

        response = self.client.post(self.login_url, {
            'email': 'valid@example.com',
            'password': 'WrongPass123'
        })

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TokenRefreshTests(TestCase):
    """Tests for JWT token refresh"""

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.activate_url = reverse('activate')
        self.token_refresh_url = reverse('token_refresh')

    def create_and_activate_user(self):
        """Helper to create and activate a user, returning refresh token"""
        register_data = {
            'username': 'refreshuser',
            'email': 'refresh@example.com',
            'password': 'TestPass123'
        }
        self.client.post(self.register_url, register_data)

        import re
        match = re.search(r'token=([^&\s]+)', mail.outbox[0].body)
        token = match.group(1)
        activate_response = self.client.get(f'{self.activate_url}?token={token}')
        mail.outbox.clear()
        return activate_response.data['refresh']

    def test_refresh_token_returns_new_access_token(self):
        """Test that valid refresh token returns new access token"""
        refresh_token = self.create_and_activate_user()

        response = self.client.post(self.token_refresh_url, {
            'refresh': refresh_token
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_refresh_token_with_invalid_token_fails(self):
        """Test that invalid refresh token returns error"""
        response = self.client.post(self.token_refresh_url, {
            'refresh': 'invalid_refresh_token_123'
        })

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TenantMiddlewareTests(TestCase):
    """Tests for JWTTenantMiddleware - tenant context extraction"""

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('register')
        self.activate_url = reverse('activate')
        self.stores_url = '/api/stores/'  # Protected endpoint
        self.token_obtain_url = reverse('token_obtain_pair')

    def create_and_activate_user(self, email, password):
        """Helper to create, activate and return tokens"""
        register_data = {
            'username': email.split('@')[0],
            'email': email,
            'password': password
        }
        self.client.post(self.register_url, register_data)

        import re
        match = re.search(r'token=([^&\s]+)', mail.outbox[0].body)
        token = match.group(1)
        activate_response = self.client.get(f'{self.activate_url}?token={token}')
        mail.outbox.clear()
        return activate_response.data['access']

    def test_middleware_sets_tenant_id_on_valid_request(self):
        """Test that middleware sets request.tenant_id for authenticated requests"""
        access_token = self.create_and_activate_user('tenant@example.com', 'TestPass123')

        # Create a view that we can test tenant_id
        # We'll use the stores list endpoint (it should work with valid token)
        response = self.client.get(
            self.stores_url,
            HTTP_AUTHORIZATION=f'Bearer {access_token}'
        )

        # 200 is expected (even if empty list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_middleware_rejects_request_without_token(self):
        """Test that middleware rejects requests without Authorization header"""
        response = self.client.get(self.stores_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_middleware_rejects_request_with_invalid_token(self):
        """Test that middleware rejects requests with invalid token"""
        response = self.client.get(
            self.stores_url,
            HTTP_AUTHORIZATION='Bearer invalid_token_123'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_super_admin_without_tenant_id_is_allowed(self):
        """Test that Super Admin can access without tenant_id"""
        # Create Super Admin user
        from users.models import User
        admin = User.objects.create_user(
            username='superadmin',
            email='admin@example.com',
            password='AdminPass123',
            is_active=True
        )
        admin.role = 'Super Admin'
        admin.tenant_id = None
        admin.save()

        # Get token for super admin
        refresh = RefreshToken.for_user(admin)
        access_token = str(refresh.access_token)

        response = self.client.get(
            self.stores_url,
            HTTP_AUTHORIZATION=f'Bearer {access_token}'
        )

        # Should be allowed (200 even if empty list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_regular_user_without_tenant_id_is_blocked(self):
        """Test that regular user without tenant_id gets 403"""
        # Create user without tenant_id
        from users.models import User
        user = User.objects.create_user(
            username='notenant',
            email='notenant@example.com',
            password='Pass123',
            is_active=True
        )
        user.tenant_id = None
        user.save()

        # Get token for user
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        response = self.client.get(
            self.stores_url,
            HTTP_AUTHORIZATION=f'Bearer {access_token}'
        )

        # Should be forbidden
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)