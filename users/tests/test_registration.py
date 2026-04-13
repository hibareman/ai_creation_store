from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.models import User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationTenantSecurityTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_register_rejects_client_supplied_tenant_id(self):
        payload = {
            "username": "mallory",
            "email": "mallory@example.com",
            "password": "StrongPass123!",
            "role": "Store Owner",
            "tenant_id": 999,
        }

        response = self.client.post("/api/auth/register/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("tenant_id", response.data)
        self.assertIn("not allowed", str(response.data["tenant_id"]).lower())
        self.assertFalse(User.objects.filter(email="mallory@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_register_rejects_super_admin_role(self):
        payload = {
            "username": "rootish",
            "email": "rootish@example.com",
            "password": "StrongPass123!",
            "role": "Super Admin",
        }

        response = self.client.post("/api/auth/register/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.data)
        self.assertFalse(User.objects.filter(email="rootish@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)
