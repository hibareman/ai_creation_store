from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User


class SuperAdminBackendCreationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_backend_controlled_superadmin_creation_command_works(self):
        out = StringIO()

        call_command(
            "bootstrap_superadmin",
            password="StrongSuperAdmin123!",
            stdout=out,
        )

        user = User.objects.get(email="superadmin@gmail.com")
        self.assertEqual(user.role, "Super Admin")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertIsNone(user.tenant_id)
        self.assertIn("Super Admin created successfully", out.getvalue())

    def test_superadmin_can_login_after_backend_creation(self):
        call_command(
            "bootstrap_superadmin",
            password="StrongSuperAdmin123!",
        )

        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "superadmin@gmail.com",
                "password": "StrongSuperAdmin123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["role"], "Super Admin")
        self.assertIsNone(response.data["tenant_id"])
