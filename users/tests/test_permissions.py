from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from users.models import User
from users.permissions import IsSuperAdmin


class _SuperAdminOnlyView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response({"detail": "ok"})


class IsSuperAdminPermissionTests(TestCase):
    def setUp(self):
        self.permission = IsSuperAdmin()
        self.factory = APIRequestFactory()

    def _request_for_user(self, user):
        return SimpleNamespace(user=user)

    def _create_user(self, *, username, email, role, tenant_id=None, is_active=True):
        return User.objects.create_user(
            username=username,
            email=email,
            password="StrongPass123!",
            role=role,
            is_active=is_active,
            tenant_id=tenant_id,
        )

    def test_is_super_admin_allows_super_admin_user(self):
        user = self._create_user(
            username="superadmin",
            email="superadmin@gmail.com",
            role="Super Admin",
            tenant_id=None,
        )

        self.assertTrue(
            self.permission.has_permission(self._request_for_user(user), view=None)
        )

    def test_is_super_admin_denies_store_owner_user(self):
        user = self._create_user(
            username="owner",
            email="owner@example.com",
            role="Store Owner",
            tenant_id=1001,
        )

        self.assertFalse(
            self.permission.has_permission(self._request_for_user(user), view=None)
        )

    def test_is_super_admin_denies_anonymous_user(self):
        request = self._request_for_user(AnonymousUser())

        self.assertFalse(self.permission.has_permission(request, view=None))

    def test_is_super_admin_denies_user_with_other_role(self):
        user = self._create_user(
            username="support",
            email="support@example.com",
            role="Support Agent",
            tenant_id=None,
        )

        self.assertFalse(
            self.permission.has_permission(self._request_for_user(user), view=None)
        )

    def test_is_super_admin_denies_inactive_super_admin_user(self):
        user = self._create_user(
            username="inactive_superadmin",
            email="inactive_superadmin@example.com",
            role="Super Admin",
            tenant_id=None,
            is_active=False,
        )

        self.assertFalse(
            self.permission.has_permission(self._request_for_user(user), view=None)
        )

    def test_is_super_admin_dummy_view_enforces_http_statuses(self):
        view = _SuperAdminOnlyView.as_view()
        super_admin = self._create_user(
            username="view_superadmin",
            email="view_superadmin@example.com",
            role="Super Admin",
            tenant_id=None,
        )
        store_owner = self._create_user(
            username="view_owner",
            email="view_owner@example.com",
            role="Store Owner",
            tenant_id=1002,
        )

        super_admin_request = self.factory.get("/_test/super-admin-only/")
        force_authenticate(super_admin_request, user=super_admin)
        self.assertEqual(view(super_admin_request).status_code, status.HTTP_200_OK)

        store_owner_request = self.factory.get("/_test/super-admin-only/")
        force_authenticate(store_owner_request, user=store_owner)
        self.assertEqual(
            view(store_owner_request).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        missing_token_request = self.factory.get("/_test/super-admin-only/")
        self.assertEqual(
            view(missing_token_request).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        invalid_token_request = self.factory.get(
            "/_test/super-admin-only/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        self.assertEqual(
            view(invalid_token_request).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )