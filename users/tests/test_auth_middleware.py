from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.core import mail
from users import services
from users.models import User


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthActivationTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_register_sends_activation_and_user_inactive(self):
        data = {
            'username': 'alice',
            'email': 'alice@example.com',
            'password': 'strongpass123'
        }

        resp = self.client.post('/api/auth/register/', data, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('Activation email sent.', resp.data.get('detail', ''))

        user = User.objects.get(email='alice@example.com')
        self.assertFalse(user.is_active)

        # One email sent with activation link containing token
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('/api/auth/activate/', body)

    def test_login_blocked_before_activation(self):
        # create inactive user
        user = User.objects.create(username='bob', email='bob@example.com', is_active=False)
        user.set_password('pw12345')
        user.save()

        resp = self.client.post('/api/auth/login/', {'email': 'bob@example.com', 'password': 'pw12345'}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Email not verified', resp.data.get('detail', ''))

    def test_login_invalid_credentials_returns_401(self):
        user = User.objects.create(username='wrongpass', email='wrongpass@example.com', is_active=True)
        user.set_password('CorrectPass123!')
        user.save()

        resp = self.client.post(
            '/api/auth/login/',
            {'email': 'wrongpass@example.com', 'password': 'WrongPass123!'},
            format='json',
        )

        self.assertEqual(resp.status_code, 401)
        self.assertIn('Invalid credentials', str(resp.data.get('detail', '')))

    def test_activation_link_activates_and_returns_tokens(self):
        # register user via service to ensure activation token semantics
        user = services.register_user(username='carol', email='carol@example.com', password='pwxyz')

        # Token is already generated during registration
        token = user.activation_token

        resp = self.client.get(f'/api/auth/activate/{token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

        user.refresh_from_db()
        self.assertTrue(user.is_active)


class MiddlewareTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def _get_auth_header_for_user(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_missing_tenant_for_non_superadmin_returns_403(self):
        # create a user without tenant_id
        user = User.objects.create(username='no_tenant', email='nont@example.com', role='Store Owner', is_active=True, tenant_id=None)
        user.set_password('pw')
        user.save()

        auth = self._get_auth_header_for_user(user)
        resp = self.client.get('/api/auth/register/', HTTP_AUTHORIZATION=auth)
        self.assertEqual(resp.status_code, 403)
        self.assertIn('tenant_id missing', resp.json().get('detail', ''))

    def test_super_admin_without_tenant_allowed(self):
        user = User.objects.create(username='sa', email='sa@example.com', role='Super Admin', is_active=True, tenant_id=None)
        user.set_password('pw')
        user.save()

        auth = self._get_auth_header_for_user(user)
        resp = self.client.get('/api/auth/register/', HTTP_AUTHORIZATION=auth)
        # middleware should allow; view doesn't accept GET so Method Not Allowed (405)
        self.assertEqual(resp.status_code, 405)

    def test_invalid_x_tenant_header_is_ignored(self):
        resp = self.client.get(
            '/api/auth/register/',
            HTTP_X_TENANT_ID='not-an-int'
        )
        # Header is ignored; endpoint itself is GET-not-allowed.
        self.assertEqual(resp.status_code, 405)
