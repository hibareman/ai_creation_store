from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from stores.models import Store
from users.models import User

from themes.models import StoreThemeConfig, ThemeTemplate


class ThemeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="theme_owner",
            email="theme_owner@example.com",
            password="pass123",
        )
        self.owner.is_active = True
        self.owner.tenant_id = 100
        self.owner.save()

        self.same_tenant_non_owner = User.objects.create_user(
            username="same_tenant_user",
            email="same_tenant@example.com",
            password="pass123",
        )
        self.same_tenant_non_owner.is_active = True
        self.same_tenant_non_owner.tenant_id = 100
        self.same_tenant_non_owner.save()

        self.other_tenant_user = User.objects.create_user(
            username="other_tenant_user",
            email="other_tenant@example.com",
            password="pass123",
        )
        self.other_tenant_user.is_active = True
        self.other_tenant_user.tenant_id = 200
        self.other_tenant_user.save()

        self.store = Store.objects.create(
            owner=self.owner,
            name="Theme Store",
            tenant_id=100,
        )

        self.modern_template = ThemeTemplate.objects.get(name="Modern")
        self.minimal_template = ThemeTemplate.objects.get(name="Minimal")

        self.theme_config = StoreThemeConfig.objects.create(
            store=self.store,
            theme_template=self.modern_template,
            primary_color="#111111",
            secondary_color="#222222",
            font_family="Inter",
            logo_url="https://example.com/logo.png",
            banner_url="https://example.com/banner.png",
        )

        self.owner_auth_header = self._build_auth_header(self.owner)
        self.same_tenant_non_owner_auth_header = self._build_auth_header(
            self.same_tenant_non_owner
        )
        self.other_tenant_auth_header = self._build_auth_header(self.other_tenant_user)

    def _build_auth_header(self, user):
        refresh = RefreshToken.for_user(user)
        return f"Bearer {str(refresh.access_token)}"

    def test_store_owner_can_retrieve_theme_template_list(self):
        response = self.client.get(
            f"/api/stores/{self.store.id}/themes/templates/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in response.data]
        self.assertIn("Modern", names)
        self.assertIn("Minimal", names)
        self.assertIn("Classic", names)

    def test_store_owner_can_retrieve_current_store_theme_config(self):
        response = self.client.get(
            f"/api/stores/{self.store.id}/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.theme_config.id)
        self.assertEqual(response.data["store"], self.store.id)
        self.assertEqual(response.data["theme_template"]["id"], self.modern_template.id)
        self.assertEqual(response.data["primary_color"], "#111111")

    def test_store_owner_can_update_editable_theme_fields(self):
        payload = {
            "theme_template": self.minimal_template.id,
            "primary_color": "#abcdef",
            "secondary_color": "#fedcba",
            "font_family": "Poppins",
            "logo_url": "https://example.com/new-logo.png",
            "banner_url": "https://example.com/new-banner.png",
        }

        response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.theme_config.refresh_from_db()
        self.assertEqual(self.theme_config.theme_template_id, self.minimal_template.id)
        self.assertEqual(self.theme_config.primary_color, "#abcdef")
        self.assertEqual(self.theme_config.secondary_color, "#fedcba")
        self.assertEqual(self.theme_config.font_family, "Poppins")
        self.assertEqual(self.theme_config.logo_url, "https://example.com/new-logo.png")
        self.assertEqual(
            self.theme_config.banner_url, "https://example.com/new-banner.png"
        )

    def test_non_owner_cannot_access_or_modify_store_theme(self):
        templates_response = self.client.get(
            f"/api/stores/{self.store.id}/themes/templates/",
            HTTP_AUTHORIZATION=self.same_tenant_non_owner_auth_header,
        )
        self.assertEqual(templates_response.status_code, status.HTTP_403_FORBIDDEN)

        get_response = self.client.get(
            f"/api/stores/{self.store.id}/theme/",
            HTTP_AUTHORIZATION=self.same_tenant_non_owner_auth_header,
        )
        self.assertEqual(get_response.status_code, status.HTTP_403_FORBIDDEN)

        patch_response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            {"primary_color": "#999999"},
            format="json",
            HTTP_AUTHORIZATION=self.same_tenant_non_owner_auth_header,
        )
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

        self.theme_config.refresh_from_db()
        self.assertEqual(self.theme_config.primary_color, "#111111")

    def test_different_tenant_cannot_access_it(self):
        templates_response = self.client.get(
            f"/api/stores/{self.store.id}/themes/templates/",
            HTTP_AUTHORIZATION=self.other_tenant_auth_header,
        )
        self.assertEqual(templates_response.status_code, status.HTTP_403_FORBIDDEN)

        detail_response = self.client.get(
            f"/api/stores/{self.store.id}/theme/",
            HTTP_AUTHORIZATION=self.other_tenant_auth_header,
        )
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

        patch_response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            {"primary_color": "#333333"},
            format="json",
            HTTP_AUTHORIZATION=self.other_tenant_auth_header,
        )
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_or_non_existent_theme_template_cannot_be_used(self):
        response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            {"theme_template": 999999},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.theme_config.refresh_from_db()
        self.assertEqual(self.theme_config.theme_template_id, self.modern_template.id)
