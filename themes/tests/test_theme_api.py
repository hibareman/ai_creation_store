# test file for themes
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

        # Create theme templates first (since they don't exist by default)
        self.modern_template = ThemeTemplate.objects.create(
            name="Modern",
            description="Modern template with clean design"
        )
        self.minimal_template = ThemeTemplate.objects.create(
            name="Minimal",
            description="Minimal template with simple design"
        )
        self.classic_template = ThemeTemplate.objects.create(
            name="Classic",
            description="Classic template with traditional design"
        )

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

    @staticmethod
    def _payload(response):
        return response.json()

    def test_store_owner_can_retrieve_theme_template_list(self):
        response = self.client.get(
            f"/api/stores/{self.store.id}/themes/templates/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        names = [item["name"] for item in data]
        self.assertIn("Modern", names)
        self.assertIn("Minimal", names)
        self.assertIn("Classic", names)

    def test_store_owner_can_retrieve_current_store_theme_config(self):
        response = self.client.get(
            f"/api/stores/{self.store.id}/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["id"], self.theme_config.id)
        self.assertEqual(data["store"], self.store.id)
        self.assertEqual(data["theme_template"]["id"], self.modern_template.id)
        self.assertEqual(data["primary_color"], "#111111")

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

    def test_store_without_theme_config_returns_default_payload(self):
        # Create a new store without theme config
        new_store = Store.objects.create(
            owner=self.owner,
            name="New Store Without Theme",
            tenant_id=100,
        )

        response = self.client.get(
            f"/api/stores/{new_store.id}/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertIsNone(data["id"])
        self.assertEqual(data["store"], new_store.id)
        self.assertEqual(data["primary_color"], "#4F46E5")
        self.assertEqual(data["secondary_color"], "#FFFFFF")
        self.assertEqual(data["font_family"], "Inter")
        self.assertEqual(data["logo_url"], "")
        self.assertEqual(data["banner_url"], "")
        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())
        self.assertIsNotNone(data["theme_template"])

    def test_store_without_appearance_config_returns_default_payload(self):
        new_store = Store.objects.create(
            owner=self.owner,
            name="New Store Without Appearance",
            tenant_id=100,
        )

        response = self.client.get(
            f"/api/stores/{new_store.id}/appearance/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["store_id"], str(new_store.slug or new_store.id))
        self.assertEqual(data["appearance"]["primaryColor"], "#4F46E5")
        self.assertEqual(data["appearance"]["backgroundColor"], "#FFFFFF")
        self.assertEqual(data["appearance"]["font"], "Inter")
        self.assertEqual(data["appearance"]["logoUrl"], "")
        self.assertIsInstance(data["appearance"]["style"], str)
        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())

    def test_store_with_theme_config_returns_saved_appearance_values(self):
        response = self.client.get(
            f"/api/stores/{self.store.id}/appearance/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["store_id"], str(self.store.slug or self.store.id))
        self.assertEqual(data["appearance"]["primaryColor"], "#111111")
        self.assertEqual(data["appearance"]["backgroundColor"], "#222222")
        self.assertEqual(data["appearance"]["font"], "Inter")
        self.assertEqual(data["appearance"]["style"], "modern")
        self.assertEqual(data["appearance"]["logoUrl"], "https://example.com/logo.png")

    def test_missing_store_still_returns_404_for_theme_and_appearance(self):
        theme_response = self.client.get(
            "/api/stores/999999/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )
        self.assertEqual(theme_response.status_code, status.HTTP_404_NOT_FOUND)

        appearance_response = self.client.get(
            "/api/stores/999999/appearance/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )
        self.assertEqual(appearance_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_and_tenant_access_rules_unchanged_for_appearance(self):
        same_tenant_non_owner_response = self.client.get(
            f"/api/stores/{self.store.id}/appearance/",
            HTTP_AUTHORIZATION=self.same_tenant_non_owner_auth_header,
        )
        self.assertEqual(same_tenant_non_owner_response.status_code, status.HTTP_403_FORBIDDEN)

        other_tenant_response = self.client.get(
            f"/api/stores/{self.store.id}/appearance/",
            HTTP_AUTHORIZATION=self.other_tenant_auth_header,
        )
        self.assertEqual(other_tenant_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_theme_config_for_store_without_config(self):
        # Create a new store without theme config
        new_store = Store.objects.create(
            owner=self.owner,
            name="New Store For Creation",
            tenant_id=100,
        )

        payload = {
            "theme_template": self.minimal_template.id,
            "primary_color": "#333333",
            "secondary_color": "#444444",
            "font_family": "Roboto",
            "logo_url": "https://example.com/logo2.png",
            "banner_url": "https://example.com/banner2.png",
        }

        response = self.client.patch(
            f"/api/stores/{new_store.id}/theme/",
            payload,
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["store"], new_store.id)
        self.assertEqual(data["theme_template"]["id"], self.minimal_template.id)
        self.assertEqual(data["primary_color"], "#333333")
        self.assertEqual(data["secondary_color"], "#444444")
        self.assertEqual(data["font_family"], "Roboto")
        self.assertEqual(data["logo_url"], "https://example.com/logo2.png")
        self.assertEqual(data["banner_url"], "https://example.com/banner2.png")

    def test_partial_update_theme_config(self):
        response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            {"primary_color": "#ff0000", "font_family": "Arial"},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["primary_color"], "#ff0000")
        self.assertEqual(data["font_family"], "Arial")
        self.assertEqual(data["secondary_color"], "#222222")  # unchanged
        self.assertEqual(data["theme_template"]["id"], self.modern_template.id)  # unchanged

    def test_empty_strings_for_logo_and_banner_are_accepted(self):
        response = self.client.patch(
            f"/api/stores/{self.store.id}/theme/",
            {"logo_url": "", "banner_url": ""},
            format="json",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = self._payload(response)
        self.assertEqual(data["logo_url"], "")
        self.assertEqual(data["banner_url"], "")
    def test_repeated_theme_fallback_reads_do_not_create_db_record(self):
        new_store = Store.objects.create(
            owner=self.owner,
            name="Fallback Theme Store",
            tenant_id=100,
        )
        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())

        first_response = self.client.get(
            f"/api/stores/{new_store.id}/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )
        second_response = self.client.get(
            f"/api/stores/{new_store.id}/theme/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        first_payload = self._payload(first_response)
        second_payload = self._payload(second_response)

        self.assertIsNone(first_payload["id"])
        self.assertIsNone(second_payload["id"])
        self.assertEqual(first_payload["store"], new_store.id)
        self.assertEqual(second_payload["store"], new_store.id)
        self.assertEqual(first_payload["primary_color"], "#4F46E5")
        self.assertEqual(second_payload["primary_color"], "#4F46E5")
        self.assertEqual(first_payload["secondary_color"], "#FFFFFF")
        self.assertEqual(second_payload["secondary_color"], "#FFFFFF")

        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())

    def test_repeated_appearance_fallback_reads_do_not_create_db_record(self):
        new_store = Store.objects.create(
            owner=self.owner,
            name="Fallback Appearance Store",
            tenant_id=100,
        )
        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())

        first_response = self.client.get(
            f"/api/stores/{new_store.id}/appearance/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )
        second_response = self.client.get(
            f"/api/stores/{new_store.id}/appearance/",
            HTTP_AUTHORIZATION=self.owner_auth_header,
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        first_payload = self._payload(first_response)
        second_payload = self._payload(second_response)

        self.assertEqual(first_payload["store_id"], str(new_store.slug or new_store.id))
        self.assertEqual(second_payload["store_id"], str(new_store.slug or new_store.id))
        self.assertEqual(first_payload["appearance"]["primaryColor"], "#4F46E5")
        self.assertEqual(second_payload["appearance"]["primaryColor"], "#4F46E5")
        self.assertEqual(first_payload["appearance"]["backgroundColor"], "#FFFFFF")
        self.assertEqual(second_payload["appearance"]["backgroundColor"], "#FFFFFF")
        self.assertEqual(first_payload["appearance"]["font"], "Inter")
        self.assertEqual(second_payload["appearance"]["font"], "Inter")

        self.assertFalse(StoreThemeConfig.objects.filter(store=new_store).exists())