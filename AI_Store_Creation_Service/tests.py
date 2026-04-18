import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store
from themes.models import StoreThemeConfig, ThemeTemplate

from .draft_store import (
    get_ai_draft,
    get_ai_draft_meta,
    save_ai_draft,
    save_ai_draft_meta,
)
from .serializers import (
    AIApplyDraftResponseSerializer,
    AIClarificationRequestSerializer,
    AIDraftStateResponseSerializer,
    AIRegenerateSectionRequestSerializer,
    AIStartDraftRequestSerializer,
    EmptySerializer,
)
from .services import (
    apply_current_ai_draft_categories,
    apply_current_ai_draft_products,
    apply_current_ai_draft_to_store,
    apply_current_ai_draft_store_core,
    create_draft_store_for_ai_flow,
    generate_initial_store_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
)
from .views import (
    AIApplyDraftAPIView,
    AIClarificationAPIView,
    AICurrentDraftAPIView,
    AIRegenerateDraftAPIView,
    AIRegenerateSectionAPIView,
    AIStartDraftAPIView,
)
from .validators import build_ai_fallback_payload


User = get_user_model()


class AICreationServicesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="ai_owner",
            email="ai_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

    def _create_store(self) -> Store:
        return Store.objects.create(
            owner=self.user,
            tenant_id=self.user.tenant_id,
            name="AI Draft Store",
            description="",
            status="draft",
        )

    def _seed_templates(self):
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return {
            "store": {"name": "My Store", "description": "Desc"},
            "store_settings": {"currency": "USD", "language": "en", "timezone": "UTC"},
            "theme": {
                "theme_template": "Modern",
                "primary_color": "#112233",
                "secondary_color": "rgb(255, 255, 255)",
                "font_family": "Inter",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [{"name": "Clothes"}, {"name": "Shoes"}],
            "products": [
                {
                    "name": "T-Shirt",
                    "description": "Cotton shirt",
                    "price": 25.5,
                    "sku": "TS-001",
                    "category_name": "Clothes",
                    "stock_quantity": 5,
                    "image_url": "",
                },
                {
                    "name": "Sneakers",
                    "description": "Running shoes",
                    "price": 70,
                    "sku": "SN-001",
                    "category_name": "Shoes",
                    "stock_quantity": 3,
                    "image_url": "",
                },
            ],
            "clarification_needed": False,
            "clarification_questions": [],
        }

    @staticmethod
    def _clarification_payload() -> dict:
        return {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

    def _prepare_clarification_state(self, store: Store, round_count: int = 0):
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": round_count,
                "original_user_store_description": "Original store description",
            },
        )

    def _prepare_regeneration_state(
        self,
        store: Store,
        *,
        current_draft: dict | None = None,
        original_description: str = "Original store description",
        clarification_history: list[dict] | None = None,
        latest_clarification_input: str = "Prefer minimal style",
        clarification_round_count: int = 1,
    ):
        draft_payload = current_draft if current_draft is not None else self._valid_full_draft_payload()
        history = clarification_history if clarification_history is not None else []
        save_ai_draft(store.id, draft_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": clarification_round_count,
                "original_user_store_description": original_description,
                "latest_clarification_input": latest_clarification_input,
                "clarification_history": history,
            },
        )

    def _prepare_partial_regeneration_state(
        self,
        store: Store,
        *,
        current_draft: dict | None = None,
        original_description: str = "Original store description",
        clarification_history: list[dict] | None = None,
        latest_clarification_input: str = "Prefer minimal style",
        clarification_round_count: int = 1,
    ):
        draft_payload = current_draft if current_draft is not None else self._valid_full_draft_payload()
        history = clarification_history if clarification_history is not None else []
        save_ai_draft(store.id, draft_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": clarification_round_count,
                "original_user_store_description": original_description,
                "latest_clarification_input": latest_clarification_input,
                "clarification_history": history,
            },
        )

    def test_create_draft_store_success_with_trusted_context(self):
        store = create_draft_store_for_ai_flow(
            user=self.user,
            tenant_id=101,
            name="My Draft",
            description="Test description",
        )

        self.assertTrue(Store.objects.filter(id=store.id).exists())
        self.assertEqual(store.owner_id, self.user.id)
        self.assertEqual(store.tenant_id, 101)
        self.assertEqual(store.status, "draft")

    def test_create_draft_store_rejects_invalid_contexts(self):
        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=AnonymousUser(),
                tenant_id=101,
                name="My Draft",
            )

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id=None,
                name="My Draft",
            )

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id=999,
                name="My Draft",
            )

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id=101,
                name="   ",
            )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_success_full_draft(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        valid_full_draft = {
            "store": {"name": "My Store", "description": "Desc"},
            "store_settings": {"currency": "USD", "language": "en", "timezone": "UTC"},
            "theme": {
                "theme_template": "Modern",
                "primary_color": "#112233",
                "secondary_color": "rgb(255, 255, 255)",
                "font_family": "Inter",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [{"name": "Clothes"}, {"name": "Shoes"}],
            "products": [
                {
                    "name": "T-Shirt",
                    "description": "Cotton shirt",
                    "price": 25.5,
                    "sku": "TS-001",
                    "category_name": "Clothes",
                    "stock_quantity": 5,
                    "image_url": "",
                },
                {
                    "name": "Sneakers",
                    "description": "Running shoes",
                    "price": 70,
                    "sku": "SN-001",
                    "category_name": "Shoes",
                    "stock_quantity": 3,
                    "image_url": "",
                },
            ],
            "clarification_needed": False,
            "clarification_questions": [],
        }

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = self._as_provider_response(valid_full_draft)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result, valid_full_draft)
        self.assertEqual(get_ai_draft(store.id), valid_full_draft)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["current_step"], "setting_up_store_configuration")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])
        self.assertEqual(
            meta["original_user_store_description"],
            "A modern sportswear store",
        )

    @patch("AI_Store_Creation_Service.services.validate_products_section")
    @patch("AI_Store_Creation_Service.services.validate_categories_section")
    @patch("AI_Store_Creation_Service.services.validate_theme_section")
    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_clarification_mode_skips_full_validators(
        self,
        mock_get_provider,
        mock_validate_theme,
        mock_validate_categories,
        mock_validate_products,
    ):
        store = self._create_store()
        self._seed_templates()

        clarification_payload = {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = self._as_provider_response(
            clarification_payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertEqual(result, clarification_payload)
        self.assertEqual(get_ai_draft(store.id), clarification_payload)
        mock_validate_theme.assert_not_called()
        mock_validate_categories.assert_not_called()
        mock_validate_products.assert_not_called()

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["current_step"], "analyzing_description")
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_on_parsing_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = {"choices": []}

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any description",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["current_step"], "analyzing_description")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_on_validation_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        invalid_payload = {
            "store": {"name": "My Store", "description": "Desc"},
            "store_settings": {"currency": "USD", "language": "en", "timezone": "UTC"},
            "theme": {
                "theme_template": "Modern",
                "primary_color": "#112233",
                "secondary_color": "#ffffff",
                "font_family": "Inter",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [{"name": "Clothes"}, {"name": "Shoes"}],
            "products": [],
            "clarification_needed": False,
            "clarification_questions": [],
        }

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = self._as_provider_response(invalid_payload)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any description",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_when_theme_template_not_available(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()

        invalid_template_payload = self._valid_full_draft_payload()
        invalid_template_payload["theme"]["theme_template"] = "UnknownTemplate"

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = self._as_provider_response(
            invalid_template_payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any description",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_on_provider_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.side_effect = RuntimeError("provider timeout")

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any description",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["current_step"], "analyzing_description")
        self.assertTrue(meta["is_fallback"])
    def test_create_draft_store_rejects_invalid_description_type(self):
        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id=101,
                name="My Draft",
                description=123,  # invalid
            )

    def test_create_draft_store_rejects_invalid_tenant_id_values(self):
        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id=-1,
                name="My Draft",
            )

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(
                user=self.user,
                tenant_id="abc",
                name="My Draft",
            )

    def test_generate_initial_store_draft_rejects_store_not_found_or_access_denied(self):
        self._seed_templates()

        with self.assertRaises(ValidationError):
            generate_initial_store_draft(
                store_id=999999,
                user=self.user,
                tenant_id=101,
                user_store_description="Any description",
            )

    def test_generate_initial_store_draft_rejects_when_no_theme_templates_exist(self):
        store = self._create_store()

        with patch(
            "AI_Store_Creation_Service.services.get_available_theme_template_names",
            return_value=[],
        ), patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                generate_initial_store_draft(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    user_store_description="Any description",
                )
            mock_get_provider.assert_not_called()

        self.assertIn("No available theme templates found", str(exc.exception))

    @patch("AI_Store_Creation_Service.services.validate_products_section")
    @patch("AI_Store_Creation_Service.services.validate_categories_section")
    @patch("AI_Store_Creation_Service.services.validate_theme_section")
    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_saves_original_description_in_clarification_metadata(
        self,
        mock_get_provider,
        mock_validate_theme,
        mock_validate_categories,
        mock_validate_products,
    ):
        store = self._create_store()
        self._seed_templates()

        clarification_payload = {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.return_value = self._as_provider_response(
            clarification_payload
        )

        original_description = "Need help defining the store idea"

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description=original_description,
        )

        self.assertEqual(result, clarification_payload)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(
            meta["original_user_store_description"],
            original_description,
        )
        mock_validate_theme.assert_not_called()
        mock_validate_categories.assert_not_called()
        mock_validate_products.assert_not_called()

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_saves_original_description_in_fallback_metadata(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()

        mock_provider = mock_get_provider.return_value
        mock_provider.generate_store_draft.side_effect = RuntimeError("provider timeout")

        original_description = "Fallback should still preserve this description"

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description=original_description,
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(
            meta["original_user_store_description"],
            original_description,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_success_stays_in_clarification(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=0)

        mock_provider = mock_get_provider.return_value
        next_clarification_payload = self._clarification_payload()
        mock_provider.clarify_store_draft.return_value = self._as_provider_response(
            next_clarification_payload
        )

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        self.assertEqual(result, next_clarification_payload)
        self.assertEqual(get_ai_draft(store.id), next_clarification_payload)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["mode"], "clarification")
        self.assertEqual(meta["clarification_round_count"], 1)
        self.assertEqual(meta["current_step"], "analyzing_description")

    @patch("AI_Store_Creation_Service.services.validate_products_section")
    @patch("AI_Store_Creation_Service.services.validate_categories_section")
    @patch("AI_Store_Creation_Service.services.validate_theme_section")
    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_success_transitions_to_draft_ready(
        self,
        mock_get_provider,
        mock_validate_theme,
        mock_validate_categories,
        mock_validate_products,
    ):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=0)

        full_payload = self._valid_full_draft_payload()
        mock_provider = mock_get_provider.return_value
        mock_provider.clarify_store_draft.return_value = self._as_provider_response(full_payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Target audience: young adults",
        )

        self.assertEqual(result, full_payload)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertEqual(meta["current_step"], "setting_up_store_configuration")
        self.assertEqual(meta["clarification_round_count"], 1)
        mock_validate_theme.assert_called_once()
        mock_validate_categories.assert_called_once()
        mock_validate_products.assert_called_once()

    def test_process_clarification_round_rejects_when_state_not_needs_clarification(self):
        store = self._create_store()
        save_ai_draft(store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Original",
            },
        )

        with self.assertRaises(ValidationError):
            process_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers="Any answer",
            )

    def test_process_clarification_round_rejects_when_no_temporary_draft_exists(self):
        store = self._create_store()

        with self.assertRaises(ValidationError):
            process_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers="Any answer",
            )

    def test_process_clarification_round_enforces_round_limit_with_fallback(self):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=3)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])
        self.assertIn("limit", meta["reason"].lower())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_fallback_on_provider_failure(self, mock_get_provider):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)

        mock_provider = mock_get_provider.return_value
        mock_provider.clarify_store_draft.side_effect = RuntimeError("provider timeout")

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_fallback_on_parsing_failure(self, mock_get_provider):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)

        mock_provider = mock_get_provider.return_value
        mock_provider.clarify_store_draft.return_value = {"choices": []}

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_fallback_on_validation_failure(self, mock_get_provider):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)

        invalid_payload = dict(self._clarification_payload())
        invalid_payload["clarification_needed"] = False
        invalid_payload["clarification_questions"] = [{"x": 1}]

        mock_provider = mock_get_provider.return_value
        mock_provider.clarify_store_draft.return_value = self._as_provider_response(invalid_payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    def test_process_clarification_round_invalid_input_does_not_set_processing_state(self):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)
        before_meta = get_ai_draft_meta(store.id).copy()

        with self.assertRaises(ValidationError):
            process_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers="   ",
            )

        after_meta = get_ai_draft_meta(store.id)
        self.assertEqual(after_meta["status"], before_meta["status"])
        self.assertEqual(after_meta["current_step"], before_meta["current_step"])
        self.assertNotEqual(after_meta["status"], "processing")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_saves_clarification_history_for_reuse(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)

        mock_provider = mock_get_provider.return_value
        mock_provider.clarify_store_draft.return_value = self._as_provider_response(
            self._clarification_payload()
        )

        process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"target_audience": "young adults"},
        )
        process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Prefer minimal style",
        )

        meta = get_ai_draft_meta(store.id)
        self.assertIn("clarification_history", meta)
        self.assertEqual(len(meta["clarification_history"]), 2)
        self.assertIn("latest_clarification_input", meta)
        self.assertEqual(
            meta["latest_clarification_input"],
            "Prefer minimal style",
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_success_full_draft(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        current_draft = self._clarification_payload()
        clarification_history = [
            {"round": 1, "clarification_input": "Store type: Fashion"},
            {"round": 2, "clarification_input": "Audience: young adults"},
        ]
        self._prepare_regeneration_state(
            store,
            current_draft=current_draft,
            original_description="  Original idea for store  ",
            clarification_history=clarification_history,
            latest_clarification_input="Audience: young adults",
            clarification_round_count=2,
        )

        full_payload = self._valid_full_draft_payload()
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.return_value = self._as_provider_response(full_payload)

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(result, full_payload)
        self.assertEqual(get_ai_draft(store.id), full_payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["current_step"], "setting_up_store_configuration")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])
        self.assertEqual(meta["original_user_store_description"], "Original idea for store")
        self.assertEqual(meta["clarification_history"], clarification_history)
        self.assertEqual(meta["latest_clarification_input"], "Audience: young adults")
        self.assertEqual(meta["clarification_round_count"], 2)

        called_kwargs = mock_provider.regenerate_store_draft.call_args.kwargs
        self.assertEqual(called_kwargs["store_id"], store.id)
        self.assertEqual(called_kwargs["original_store_description"], "Original idea for store")
        self.assertEqual(called_kwargs["current_draft"], current_draft)
        self.assertEqual(
            called_kwargs["clarification_context"],
            {
                "clarification_history": clarification_history,
                "latest_clarification_input": "Audience: young adults",
            },
        )
        self.assertIn("Modern", called_kwargs["available_theme_templates"])
        self.assertIn("Classic", called_kwargs["available_theme_templates"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_success_clarification_mode(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        clarification_history = [{"round": 1, "clarification_input": "Store type: Fashion"}]
        self._prepare_regeneration_state(
            store,
            current_draft=self._valid_full_draft_payload(),
            original_description="Original store description",
            clarification_history=clarification_history,
            latest_clarification_input="Store type: Fashion",
            clarification_round_count=1,
        )

        clarification_payload = self._clarification_payload()
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.return_value = self._as_provider_response(
            clarification_payload
        )

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(result, clarification_payload)
        self.assertEqual(get_ai_draft(store.id), clarification_payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["current_step"], "analyzing_description")
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])
        self.assertEqual(meta["original_user_store_description"], "Original store description")
        self.assertEqual(meta["clarification_history"], clarification_history)
        self.assertEqual(meta["latest_clarification_input"], "Store type: Fashion")
        self.assertEqual(meta["clarification_round_count"], 1)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_fallback_on_provider_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.side_effect = RuntimeError("provider timeout")

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["current_step"], "analyzing_description")
        self.assertTrue(meta["is_fallback"])
        self.assertIn("provider timeout", meta["reason"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_fallback_on_parsing_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.return_value = {"choices": []}

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_fallback_on_validation_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["clarification_needed"] = False
        invalid_payload["clarification_questions"] = ["unexpected"]

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.return_value = self._as_provider_response(
            invalid_payload
        )

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_fallback_when_theme_template_not_available(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        invalid_template_payload = self._valid_full_draft_payload()
        invalid_template_payload["theme"]["theme_template"] = "UnknownTemplate"

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft.return_value = self._as_provider_response(
            invalid_template_payload
        )

        result = regenerate_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        expected_fallback = build_ai_fallback_payload()
        self.assertEqual(result, expected_fallback)
        self.assertEqual(get_ai_draft(store.id), expected_fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    def test_regenerate_store_draft_rejects_when_no_temporary_draft_exists(self):
        store = self._create_store()
        self._seed_templates()

        with self.assertRaises(ValidationError) as exc:
            regenerate_store_draft(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("No temporary AI draft found for this store", str(exc.exception))

    def test_regenerate_store_draft_rejects_when_original_description_missing(self):
        store = self._create_store()
        self._seed_templates()
        save_ai_draft(store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
            },
        )

        with self.assertRaises(ValidationError) as exc:
            regenerate_store_draft(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn(
            "Original user store description is missing from draft metadata",
            str(exc.exception),
        )

    def test_regenerate_store_draft_rejects_when_no_theme_templates_exist(self):
        store = self._create_store()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with patch(
            "AI_Store_Creation_Service.services.get_available_theme_template_names",
            return_value=[],
        ), patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                regenerate_store_draft(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                )
            mock_get_provider.assert_not_called()

        self.assertIn("No available theme templates found", str(exc.exception))

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_success_theme(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        clarification_history = [{"round": 1, "clarification_input": "Audience: youth"}]
        self._prepare_partial_regeneration_state(
            store,
            current_draft=base_draft,
            original_description="  Original partial description  ",
            clarification_history=clarification_history,
            latest_clarification_input="Audience: youth",
            clarification_round_count=1,
        )

        replacement_theme = {
            "theme_template": "Classic",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": replacement_theme}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="theme",
        )

        expected_draft = json.loads(json.dumps(base_draft))
        expected_draft["theme"] = replacement_theme
        self.assertEqual(result, expected_draft)
        self.assertEqual(get_ai_draft(store.id), expected_draft)
        self.assertEqual(result["categories"], base_draft["categories"])
        self.assertEqual(result["products"], base_draft["products"])

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertEqual(meta["current_step"], "setting_up_store_configuration")
        self.assertEqual(meta["original_user_store_description"], "Original partial description")
        self.assertEqual(meta["clarification_history"], clarification_history)
        self.assertEqual(meta["last_partial_regeneration_target_section"], "theme")

        called_kwargs = mock_provider.regenerate_store_draft_section.call_args.kwargs
        self.assertEqual(called_kwargs["target_section"], "theme")
        self.assertIn("Modern", called_kwargs["available_theme_templates"])
        self.assertIn("Classic", called_kwargs["available_theme_templates"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_success_categories(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)

        replacement_categories = [
            {"name": "Clothes"},
            {"name": "Shoes"},
            {"name": "Accessories"},
        ]
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"categories": replacement_categories}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="categories",
        )

        expected_draft = json.loads(json.dumps(base_draft))
        expected_draft["categories"] = replacement_categories
        self.assertEqual(result, expected_draft)
        self.assertEqual(get_ai_draft(store.id), expected_draft)
        self.assertEqual(result["products"], base_draft["products"])

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["last_partial_regeneration_target_section"], "categories")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_success_products(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)

        replacement_products = [
            {
                "name": "Hoodie",
                "description": "Warm hoodie",
                "price": 45,
                "sku": "HD-001",
                "category_name": "Clothes",
                "stock_quantity": 7,
                "image_url": "",
            },
            {
                "name": "Sneaker Pro",
                "description": "Pro running shoe",
                "price": 120,
                "sku": "SN-777",
                "category_name": "Shoes",
                "stock_quantity": 4,
                "image_url": "",
            },
        ]
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"products": replacement_products}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="products",
        )

        expected_draft = json.loads(json.dumps(base_draft))
        expected_draft["products"] = replacement_products
        self.assertEqual(result, expected_draft)
        self.assertEqual(get_ai_draft(store.id), expected_draft)
        self.assertEqual(result["categories"], base_draft["categories"])

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["last_partial_regeneration_target_section"], "products")

    def test_regenerate_store_draft_section_rejects_unsupported_target_section(self):
        store = self._create_store()
        self._prepare_partial_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                regenerate_store_draft_section(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    target_section="store",
                )
            mock_get_provider.assert_not_called()
        self.assertIn("target_section must be one of", str(exc.exception))

    def test_regenerate_store_draft_section_rejects_when_state_not_draft_ready(self):
        store = self._create_store()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                regenerate_store_draft_section(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    target_section="theme",
                )
            mock_get_provider.assert_not_called()
        self.assertIn("draft_ready", str(exc.exception))

    def test_regenerate_store_draft_section_rejects_when_no_temporary_draft_exists(self):
        store = self._create_store()
        self._seed_templates()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                regenerate_store_draft_section(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    target_section="theme",
                )
            mock_get_provider.assert_not_called()
        self.assertIn("No temporary AI draft found for this store", str(exc.exception))

    def test_regenerate_store_draft_section_rejects_when_original_description_missing(self):
        store = self._create_store()
        self._seed_templates()
        save_ai_draft(store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
            },
        )

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            with self.assertRaises(ValidationError) as exc:
                regenerate_store_draft_section(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    target_section="theme",
                )
            mock_get_provider.assert_not_called()
        self.assertIn(
            "Original user store description is missing from draft metadata",
            str(exc.exception),
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_provider_failure_leaves_draft_unchanged(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)
        before_draft = json.loads(json.dumps(get_ai_draft(store.id)))

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.side_effect = RuntimeError("provider timeout")

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="theme",
            )

        self.assertEqual(get_ai_draft(store.id), before_draft)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertIn("provider timeout", meta["last_partial_regeneration_error"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_parsing_failure_leaves_draft_unchanged(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)
        before_draft = json.loads(json.dumps(get_ai_draft(store.id)))

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = {"choices": []}

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="theme",
            )

        self.assertEqual(get_ai_draft(store.id), before_draft)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertIn("choices", meta["last_partial_regeneration_error"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_validation_failure_leaves_draft_unchanged(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)
        before_draft = json.loads(json.dumps(get_ai_draft(store.id)))

        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"products": [{"name": "OnlyOne"}]}
        )

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="products",
            )

        self.assertEqual(get_ai_draft(store.id), before_draft)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_theme_template_not_available_leaves_draft_unchanged(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)
        before_draft = json.loads(json.dumps(get_ai_draft(store.id)))

        invalid_theme = {
            "theme_template": "UnknownTemplate",
            "primary_color": "#222222",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": invalid_theme}
        )

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="theme",
            )

        self.assertEqual(get_ai_draft(store.id), before_draft)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_categories_invalidating_products_fails_and_keeps_draft(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        base_draft = json.loads(json.dumps(self._valid_full_draft_payload()))
        self._prepare_partial_regeneration_state(store, current_draft=base_draft)
        before_draft = json.loads(json.dumps(get_ai_draft(store.id)))

        replacement_categories = [{"name": "Electronics"}, {"name": "Books"}]
        mock_provider = mock_get_provider.return_value
        mock_provider.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"categories": replacement_categories}
        )

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="categories",
            )

        self.assertEqual(get_ai_draft(store.id), before_draft)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")

    def test_apply_current_ai_draft_store_core_success_creates_theme_config(self):
        store = self._create_store()
        self._seed_templates()

        draft_payload = self._valid_full_draft_payload()
        draft_payload["store"]["name"] = "Applied Store Name"
        draft_payload["store"]["description"] = "Applied description"
        draft_payload["theme"]["theme_template"] = "Modern"
        draft_payload["theme"]["primary_color"] = "#111111"
        draft_payload["theme"]["secondary_color"] = "rgb(250, 250, 250)"
        draft_payload["theme"]["font_family"] = "Poppins"
        draft_payload["theme"]["logo_url"] = ""
        draft_payload["theme"]["banner_url"] = ""

        self._prepare_partial_regeneration_state(store, current_draft=draft_payload)

        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 0)

        result = apply_current_ai_draft_store_core(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        store.refresh_from_db()
        self.assertEqual(store.name, "Applied Store Name")
        self.assertEqual(store.description, "Applied description")
        self.assertEqual(store.status, "draft")

        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        cfg = StoreThemeConfig.objects.get(store=store)
        self.assertEqual(cfg.theme_template.name, "Modern")
        self.assertEqual(cfg.primary_color, "#111111")
        self.assertEqual(cfg.secondary_color, "rgb(250, 250, 250)")
        self.assertEqual(cfg.font_family, "Poppins")
        self.assertEqual(cfg.logo_url, "")
        self.assertEqual(cfg.banner_url, "")

        self.assertEqual(Category.objects.filter(store=store).count(), 0)
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(get_ai_draft(store.id), draft_payload)

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_status"], "draft_ready")
        self.assertEqual(result["store"]["name"], "Applied Store Name")
        self.assertEqual(result["theme"]["theme_template"], "Modern")

    def test_apply_current_ai_draft_store_core_success_updates_existing_theme_config(self):
        store = self._create_store()
        self._seed_templates()

        modern_template = ThemeTemplate.objects.filter(name="Modern").order_by("id").first()
        classic_template = ThemeTemplate.objects.filter(name="Classic").order_by("id").first()
        self.assertIsNotNone(modern_template)
        self.assertIsNotNone(classic_template)

        StoreThemeConfig.objects.create(
            store=store,
            theme_template=modern_template,
            primary_color="#000000",
            secondary_color="#ffffff",
            font_family="Old Font",
            logo_url="https://old-logo.example.com/logo.png",
            banner_url="https://old-logo.example.com/banner.png",
        )

        draft_payload = self._valid_full_draft_payload()
        draft_payload["store"]["name"] = "Updated Store Name"
        draft_payload["store"]["description"] = "Updated description"
        draft_payload["theme"]["theme_template"] = "Classic"
        draft_payload["theme"]["primary_color"] = "#121212"
        draft_payload["theme"]["secondary_color"] = "rgb(240, 240, 240)"
        draft_payload["theme"]["font_family"] = "Inter"
        draft_payload["theme"]["logo_url"] = ""
        draft_payload["theme"]["banner_url"] = ""

        self._prepare_partial_regeneration_state(store, current_draft=draft_payload)

        result = apply_current_ai_draft_store_core(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        cfg = StoreThemeConfig.objects.get(store=store)
        self.assertEqual(cfg.theme_template.name, "Classic")
        self.assertEqual(cfg.primary_color, "#121212")
        self.assertEqual(cfg.secondary_color, "rgb(240, 240, 240)")
        self.assertEqual(cfg.font_family, "Inter")
        self.assertEqual(cfg.logo_url, "")
        self.assertEqual(cfg.banner_url, "")
        self.assertEqual(result["theme"]["theme_template"], "Classic")

    def test_apply_current_ai_draft_store_core_rejects_when_meta_not_draft_ready(self):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("Current workflow state is not draft_ready", str(exc.exception))

    def test_apply_current_ai_draft_store_core_rejects_when_no_temporary_draft(self):
        store = self._create_store()
        self._seed_templates()
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Original description",
            },
        )

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("No temporary AI draft found for this store", str(exc.exception))

    def test_apply_current_ai_draft_store_core_rejects_when_payload_not_structurally_draft_ready(
        self,
    ):
        store = self._create_store()
        self._seed_templates()

        not_ready_payload = self._valid_full_draft_payload()
        not_ready_payload["clarification_needed"] = True
        not_ready_payload["clarification_questions"] = [
            {
                "question_key": "store_type",
                "question_text": "Store type?",
                "options": ["Fashion", "Electronics"],
            }
        ]
        self._prepare_partial_regeneration_state(store, current_draft=not_ready_payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("Current draft payload is not draft_ready", str(exc.exception))

    def test_apply_current_ai_draft_store_core_rejects_when_theme_template_not_available(self):
        store = self._create_store()
        self._seed_templates()

        invalid_theme_payload = self._valid_full_draft_payload()
        invalid_theme_payload["theme"]["theme_template"] = "UnknownTemplate"
        self._prepare_partial_regeneration_state(store, current_draft=invalid_theme_payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("must match an available ThemeTemplate name", str(exc.exception))

    @patch("AI_Store_Creation_Service.services.get_theme_template_by_exact_name", return_value=None)
    def test_apply_current_ai_draft_store_core_rejects_when_template_cannot_resolve(
        self,
        mock_get_template,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "Modern"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("does not resolve to an existing ThemeTemplate", str(exc.exception))
        mock_get_template.assert_called_once()

    @patch(
        "AI_Store_Creation_Service.services.StoreThemeConfig.objects.create",
        side_effect=RuntimeError("theme config write failed"),
    )
    def test_apply_current_ai_draft_store_core_atomic_rollback_on_theme_config_write_failure(
        self,
        mock_create,
    ):
        store = self._create_store()
        self._seed_templates()

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Name Should Rollback"
        payload["store"]["description"] = "Desc Should Rollback"
        self._prepare_partial_regeneration_state(store, current_draft=payload)
        before_draft = get_ai_draft(store.id)

        with self.assertRaises(RuntimeError):
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        store.refresh_from_db()
        self.assertEqual(store.name, "AI Draft Store")
        self.assertEqual(store.description, "")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 0)
        self.assertEqual(get_ai_draft(store.id), before_draft)
        mock_create.assert_called_once()

    def test_apply_current_ai_draft_categories_success_when_no_categories_exist(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Clothes"}, {"name": "Shoes"}]
        payload["products"][0]["category_name"] = "Clothes"
        payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_categories(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        category_names = list(
            Category.objects.filter(store=store).order_by("id").values_list("name", flat=True)
        )
        self.assertEqual(category_names, ["Clothes", "Shoes"])
        self.assertEqual(result["created_categories"], ["Clothes", "Shoes"])
        self.assertEqual(result["skipped_categories"], [])

    def test_apply_current_ai_draft_categories_success_skips_existing_and_creates_missing(self):
        store = self._create_store()
        other_store = Store.objects.create(
            owner=self.user,
            tenant_id=101,
            name="Other Store",
            description="",
            status="draft",
        )
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=other_store, tenant_id=101, name="Accessories")

        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Clothes"}, {"name": "Shoes"}, {"name": "Accessories"}]
        payload["products"][0]["category_name"] = "Clothes"
        payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_categories(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        category_names = list(
            Category.objects.filter(store=store).order_by("id").values_list("name", flat=True)
        )
        self.assertEqual(category_names, ["Clothes", "Shoes", "Accessories"])
        self.assertEqual(
            Category.objects.filter(store=store, name="Clothes").count(),
            1,
        )
        self.assertEqual(result["created_categories"], ["Shoes", "Accessories"])
        self.assertEqual(result["skipped_categories"], ["Clothes"])

    def test_apply_current_ai_draft_categories_respects_normalized_name_duplicate_handling(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="  Shoes  ")

        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "shoes"}, {"name": "Clothes"}]
        payload["products"][0]["category_name"] = "shoes"
        payload["products"][1]["category_name"] = "Clothes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_categories(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        category_names = list(
            Category.objects.filter(store=store).order_by("id").values_list("name", flat=True)
        )
        self.assertEqual(category_names, ["  Shoes  ", "Clothes"])
        self.assertEqual(result["created_categories"], ["Clothes"])
        self.assertEqual(result["skipped_categories"], ["shoes"])

    def test_apply_current_ai_draft_categories_rejects_when_meta_not_draft_ready(self):
        store = self._create_store()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_categories(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("Current workflow state is not draft_ready", str(exc.exception))

    def test_apply_current_ai_draft_categories_rejects_when_no_temporary_draft(self):
        store = self._create_store()
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Original description",
            },
        )

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_categories(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("No temporary AI draft found for this store", str(exc.exception))

    def test_apply_current_ai_draft_categories_rejects_when_payload_not_structurally_draft_ready(
        self,
    ):
        store = self._create_store()
        not_ready_payload = self._valid_full_draft_payload()
        not_ready_payload["clarification_needed"] = True
        not_ready_payload["clarification_questions"] = [
            {
                "question_key": "store_type",
                "question_text": "Store type?",
                "options": ["Fashion", "Electronics"],
            }
        ]
        self._prepare_partial_regeneration_state(store, current_draft=not_ready_payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_categories(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertIn("Current draft payload is not draft_ready", str(exc.exception))

    def test_apply_current_ai_draft_categories_rejects_when_categories_products_consistency_fails(
        self,
    ):
        store = self._create_store()
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["categories"] = [{"name": "Clothes"}, {"name": "Shoes"}]
        invalid_payload["products"][0]["category_name"] = "Electronics"
        invalid_payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=invalid_payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_categories(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("does not match generated categories", str(exc.exception))
        self.assertEqual(Category.objects.filter(store=store).count(), 0)

    def test_apply_current_ai_draft_categories_atomic_rollback_on_create_failure(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Clothes"}, {"name": "Shoes"}, {"name": "Bags"}]
        payload["products"][0]["category_name"] = "Clothes"
        payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        original_create = Category.objects.create
        call_counter = {"count": 0}

        def flaky_create(*args, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] == 2:
                raise RuntimeError("category create failed")
            return original_create(*args, **kwargs)

        with patch(
            "AI_Store_Creation_Service.services.Category.objects.create",
            side_effect=flaky_create,
        ):
            with self.assertRaises(ValidationError) as exc:
                apply_current_ai_draft_categories(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                )

        self.assertIn("Failed to apply categories from current draft", str(exc.exception))
        self.assertEqual(Category.objects.filter(store=store).count(), 0)

    def test_apply_current_ai_draft_categories_respects_task_boundaries(self):
        store = self._create_store()
        self._seed_templates()
        template = ThemeTemplate.objects.filter(name="Modern").order_by("id").first()
        self.assertIsNotNone(template)

        StoreThemeConfig.objects.create(
            store=store,
            theme_template=template,
            primary_color="#000000",
            secondary_color="#ffffff",
            font_family="Initial Font",
            logo_url="https://example.com/logo.png",
            banner_url="https://example.com/banner.png",
        )

        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Clothes"}, {"name": "Shoes"}]
        payload["products"][0]["category_name"] = "Clothes"
        payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        before_store_name = store.name
        before_store_description = store.description
        before_store_status = store.status
        before_theme = StoreThemeConfig.objects.get(store=store)
        before_theme_data = {
            "template": before_theme.theme_template.name,
            "primary_color": before_theme.primary_color,
            "secondary_color": before_theme.secondary_color,
            "font_family": before_theme.font_family,
            "logo_url": before_theme.logo_url,
            "banner_url": before_theme.banner_url,
        }
        before_meta = get_ai_draft_meta(store.id)
        before_draft = get_ai_draft(store.id)

        apply_current_ai_draft_categories(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        store.refresh_from_db()
        self.assertEqual(store.name, before_store_name)
        self.assertEqual(store.description, before_store_description)
        self.assertEqual(store.status, before_store_status)

        after_theme = StoreThemeConfig.objects.get(store=store)
        self.assertEqual(after_theme.theme_template.name, before_theme_data["template"])
        self.assertEqual(after_theme.primary_color, before_theme_data["primary_color"])
        self.assertEqual(after_theme.secondary_color, before_theme_data["secondary_color"])
        self.assertEqual(after_theme.font_family, before_theme_data["font_family"])
        self.assertEqual(after_theme.logo_url, before_theme_data["logo_url"])
        self.assertEqual(after_theme.banner_url, before_theme_data["banner_url"])

        self.assertEqual(get_ai_draft(store.id), before_draft)
        self.assertEqual(get_ai_draft_meta(store.id), before_meta)

    def test_apply_current_ai_draft_products_success_creates_inventory_and_product_image_when_present(
        self,
    ):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][0]["image_url"] = "  https://img.example.com/ts-001.jpg  "
        payload["products"][1]["sku"] = "SN-001"
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][1]["image_url"] = ""
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_products(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(result["created_products"], ["TS-001", "SN-001"])
        self.assertEqual(result["skipped_products"], [])
        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(
            Product.objects.filter(store=store, category__name="Clothes").count(),
            1,
        )
        self.assertEqual(
            Product.objects.filter(store=store, category__name="Shoes").count(),
            1,
        )
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)

        shirt = Product.objects.get(store=store, sku="TS-001")
        shoes = Product.objects.get(store=store, sku="SN-001")
        self.assertEqual(shirt.inventory.stock_quantity, 9)
        self.assertEqual(shoes.inventory.stock_quantity, 4)

        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 1)
        image_row = ProductImage.objects.get(product=shirt)
        self.assertEqual(image_row.image_url, "https://img.example.com/ts-001.jpg")

    def test_apply_current_ai_draft_products_success_creates_inventory_only_when_image_url_empty(
        self,
    ):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-010"
        payload["products"][0]["stock_quantity"] = 7
        payload["products"][0]["image_url"] = "   "
        payload["products"][1]["sku"] = "SN-010"
        payload["products"][1]["stock_quantity"] = 2
        payload["products"][1]["image_url"] = ""
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_products(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(result["created_products"], ["TS-010", "SN-010"])
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 0)

    def test_apply_current_ai_draft_products_additive_only_creates_missing_and_skips_existing_sku(
        self,
    ):
        store = self._create_store()
        clothes = Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        Product.objects.create(
            store=store,
            tenant_id=101,
            category=clothes,
            name="Existing Tee",
            description="Existing product",
            price=20,
            sku="ts-001",
        )

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-001"
        payload["products"][1]["sku"] = "SN-NEW-001"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        result = apply_current_ai_draft_products(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(result["created_products"], ["SN-NEW-001"])
        self.assertEqual(result["skipped_products"], ["TS-001"])
        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(Product.objects.filter(store=store, sku="ts-001").count(), 1)
        self.assertEqual(Product.objects.filter(store=store, sku="SN-NEW-001").count(), 1)

    def test_apply_current_ai_draft_products_rejects_when_meta_not_draft_ready(self):
        store = self._create_store()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_products(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("Current workflow state is not draft_ready", str(exc.exception))

    def test_apply_current_ai_draft_products_rejects_when_no_temporary_draft(self):
        store = self._create_store()
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Original description",
            },
        )

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_products(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("No temporary AI draft found for this store", str(exc.exception))

    def test_apply_current_ai_draft_products_rejects_when_category_cannot_resolve(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["category_name"] = "Clothes"
        payload["products"][1]["category_name"] = "Shoes"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_products(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("Failed to resolve product category_name", str(exc.exception))
        self.assertEqual(Product.objects.filter(store=store).count(), 0)

    def test_apply_current_ai_draft_products_atomic_rollback_on_create_failure(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-NEW-001"
        payload["products"][1]["sku"] = "SN-NEW-001"
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        original_create = Product.objects.create
        call_counter = {"count": 0}

        def flaky_create(*args, **kwargs):
            call_counter["count"] += 1
            if call_counter["count"] == 2:
                raise RuntimeError("product create failed")
            return original_create(*args, **kwargs)

        with patch(
            "AI_Store_Creation_Service.services.Product.objects.create",
            side_effect=flaky_create,
        ):
            with self.assertRaises(ValidationError) as exc:
                apply_current_ai_draft_products(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                )

        self.assertIn("Failed to apply products from current draft", str(exc.exception))
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 0)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 0)

    @patch(
        "AI_Store_Creation_Service.services.Inventory.objects.create",
        side_effect=RuntimeError("inventory create failed"),
    )
    def test_apply_current_ai_draft_products_atomic_rollback_on_inventory_create_failure(
        self,
        _mock_inventory_create,
    ):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-INV-001"
        payload["products"][0]["image_url"] = "https://img.example.com/a.jpg"
        payload["products"][1]["sku"] = "SN-INV-001"
        payload["products"][1]["image_url"] = ""
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_products(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("Failed to apply products from current draft", str(exc.exception))
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 0)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 0)

    @patch(
        "AI_Store_Creation_Service.services.ProductImage.objects.create",
        side_effect=RuntimeError("product image create failed"),
    )
    def test_apply_current_ai_draft_products_atomic_rollback_on_product_image_create_failure(
        self,
        _mock_product_image_create,
    ):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-IMG-001"
        payload["products"][0]["image_url"] = "https://img.example.com/fail.jpg"
        payload["products"][1]["sku"] = "SN-IMG-001"
        payload["products"][1]["image_url"] = ""
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_products(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("Failed to apply products from current draft", str(exc.exception))
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 0)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 0)

    def test_apply_current_ai_draft_products_respects_task_boundaries_and_keeps_draft_state(self):
        store = self._create_store()
        self._seed_templates()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        template = ThemeTemplate.objects.filter(name="Modern").order_by("id").first()
        self.assertIsNotNone(template)
        StoreThemeConfig.objects.create(
            store=store,
            theme_template=template,
            primary_color="#101010",
            secondary_color="#fefefe",
            font_family="Inter",
            logo_url="https://example.com/logo.png",
            banner_url="https://example.com/banner.png",
        )

        payload = self._valid_full_draft_payload()
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        before_store_name = store.name
        before_store_description = store.description
        before_store_status = store.status
        before_theme = StoreThemeConfig.objects.get(store=store)
        before_theme_data = {
            "template": before_theme.theme_template.name,
            "primary_color": before_theme.primary_color,
            "secondary_color": before_theme.secondary_color,
            "font_family": before_theme.font_family,
            "logo_url": before_theme.logo_url,
            "banner_url": before_theme.banner_url,
        }
        before_category_names = list(
            Category.objects.filter(store=store).order_by("id").values_list("name", flat=True)
        )
        before_meta = get_ai_draft_meta(store.id)
        before_draft = get_ai_draft(store.id)

        apply_current_ai_draft_products(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        store.refresh_from_db()
        self.assertEqual(store.name, before_store_name)
        self.assertEqual(store.description, before_store_description)
        self.assertEqual(store.status, before_store_status)

        after_theme = StoreThemeConfig.objects.get(store=store)
        self.assertEqual(after_theme.theme_template.name, before_theme_data["template"])
        self.assertEqual(after_theme.primary_color, before_theme_data["primary_color"])
        self.assertEqual(after_theme.secondary_color, before_theme_data["secondary_color"])
        self.assertEqual(after_theme.font_family, before_theme_data["font_family"])
        self.assertEqual(after_theme.logo_url, before_theme_data["logo_url"])
        self.assertEqual(after_theme.banner_url, before_theme_data["banner_url"])

        after_category_names = list(
            Category.objects.filter(store=store).order_by("id").values_list("name", flat=True)
        )
        self.assertEqual(after_category_names, before_category_names)
        self.assertEqual(get_ai_draft(store.id), before_draft)
        self.assertEqual(get_ai_draft_meta(store.id), before_meta)

    def test_apply_current_ai_draft_to_store_success_full_apply_and_cleanup_after_commit(self):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Final Applied Store"
        payload["store"]["description"] = "Final applied description"
        payload["theme"]["theme_template"] = "Modern"
        payload["theme"]["primary_color"] = "#111111"
        payload["theme"]["secondary_color"] = "rgb(250, 250, 250)"
        payload["theme"]["font_family"] = "Poppins"
        payload["products"][0]["sku"] = "TS-APPLY-001"
        payload["products"][1]["sku"] = "SN-APPLY-001"
        payload["products"][0]["stock_quantity"] = 11
        payload["products"][1]["stock_quantity"] = 5
        payload["products"][0]["image_url"] = "https://img.example.com/ts-apply-001.jpg"
        payload["products"][1]["image_url"] = ""
        self._prepare_partial_regeneration_state(store, current_draft=payload)

        with self.captureOnCommitCallbacks(execute=True):
            result = apply_current_ai_draft_to_store(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        store.refresh_from_db()
        self.assertEqual(store.status, "setup")
        self.assertEqual(store.name, "Final Applied Store")
        self.assertEqual(store.description, "Final applied description")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        self.assertEqual(Category.objects.filter(store=store).count(), 2)
        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 1)
        self.assertIsNone(get_ai_draft(store.id))
        self.assertIsNone(get_ai_draft_meta(store.id))

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["final_status"], "setup")
        self.assertTrue(result["store_core_applied"])
        self.assertTrue(result["draft_cleanup_scheduled"])

    @patch(
        "AI_Store_Creation_Service.services.apply_current_ai_draft_categories",
        side_effect=ValidationError("categories apply failed"),
    )
    def test_apply_current_ai_draft_to_store_atomic_rollback_on_categories_failure(
        self,
        _mock_categories_apply,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Should Rollback Name"
        payload["store"]["description"] = "Should Rollback Description"
        self._prepare_partial_regeneration_state(store, current_draft=payload)
        before_draft = get_ai_draft(store.id)
        before_meta = get_ai_draft_meta(store.id)

        with self.assertRaises(ValidationError):
            apply_current_ai_draft_to_store(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        store.refresh_from_db()
        self.assertEqual(store.status, "draft")
        self.assertEqual(store.name, "AI Draft Store")
        self.assertEqual(store.description, "")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 0)
        self.assertEqual(Category.objects.filter(store=store).count(), 0)
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(get_ai_draft(store.id), before_draft)
        self.assertEqual(get_ai_draft_meta(store.id), before_meta)

    @patch(
        "AI_Store_Creation_Service.services.apply_current_ai_draft_products",
        side_effect=ValidationError("products apply failed"),
    )
    def test_apply_current_ai_draft_to_store_atomic_rollback_on_products_failure(
        self,
        _mock_products_apply,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Should Rollback Name"
        payload["store"]["description"] = "Should Rollback Description"
        self._prepare_partial_regeneration_state(store, current_draft=payload)
        before_draft = get_ai_draft(store.id)
        before_meta = get_ai_draft_meta(store.id)

        with self.assertRaises(ValidationError):
            apply_current_ai_draft_to_store(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        store.refresh_from_db()
        self.assertEqual(store.status, "draft")
        self.assertEqual(store.name, "AI Draft Store")
        self.assertEqual(store.description, "")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 0)
        self.assertEqual(Category.objects.filter(store=store).count(), 0)
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(get_ai_draft(store.id), before_draft)
        self.assertEqual(get_ai_draft_meta(store.id), before_meta)

    def test_apply_current_ai_draft_to_store_rejects_when_meta_not_draft_ready(self):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._valid_full_draft_payload())

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_to_store(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("Current workflow state is not draft_ready", str(exc.exception))
        self.assertIsNotNone(get_ai_draft(store.id))
        self.assertIsNotNone(get_ai_draft_meta(store.id))

    def test_apply_current_ai_draft_to_store_rejects_when_no_temporary_draft(self):
        store = self._create_store()
        self._seed_templates()
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Original description",
            },
        )

        with self.assertRaises(ValidationError) as exc:
            apply_current_ai_draft_to_store(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertIn("No temporary AI draft found for this store", str(exc.exception))


class AICreationSerializersTests(SimpleTestCase):
    def test_start_request_valid_passes(self):
        serializer = AIStartDraftRequestSerializer(
            data={
                "name": "My AI Store",
                "user_store_description": "A modern sportswear shop for youth.",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_start_request_blank_name_fails(self):
        serializer = AIStartDraftRequestSerializer(
            data={
                "name": "   ",
                "user_store_description": "Valid description",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("name", serializer.errors)

    def test_start_request_blank_user_store_description_fails(self):
        serializer = AIStartDraftRequestSerializer(
            data={
                "name": "Valid Name",
                "user_store_description": "   ",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("user_store_description", serializer.errors)

    def test_draft_state_response_serializer_valid_contract(self):
        serializer = AIDraftStateResponseSerializer(
            data={
                "store_id": 10,
                "draft_payload": {"store": {"name": "Store A"}},
                "draft_metadata": {"status": "draft_ready"},
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_clarification_answers_accepts_non_empty_string(self):
        serializer = AIClarificationRequestSerializer(
            data={"clarification_answers": "Target audience: young adults"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_clarification_answers_accepts_non_empty_dict(self):
        serializer = AIClarificationRequestSerializer(
            data={"clarification_answers": {"store_type": "Fashion"}}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_clarification_answers_rejects_null_blank_empty_structures(self):
        invalid_values = [None, "   ", {}, [], ()]
        for value in invalid_values:
            serializer = AIClarificationRequestSerializer(
                data={"clarification_answers": value}
            )
            self.assertFalse(serializer.is_valid(), f"value should fail: {value!r}")
            self.assertIn("clarification_answers", serializer.errors)

    def test_regenerate_section_accepts_only_theme_categories_products(self):
        valid_values = ["theme", "categories", "products"]
        for value in valid_values:
            serializer = AIRegenerateSectionRequestSerializer(
                data={"target_section": value}
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)

        invalid_serializer = AIRegenerateSectionRequestSerializer(
            data={"target_section": "store"}
        )
        self.assertFalse(invalid_serializer.is_valid())
        self.assertIn("target_section", invalid_serializer.errors)

    def test_apply_response_serializer_validates_contract_with_draft_cleanup_scheduled(self):
        serializer = AIApplyDraftResponseSerializer(
            data={
                "store_id": 20,
                "final_status": "setup",
                "store_core_applied": True,
                "categories": {
                    "created": ["Clothes", "Shoes"],
                    "skipped": [],
                },
                "products": {
                    "created": ["TS-001"],
                    "skipped": ["SN-001"],
                },
                "draft_cleanup_scheduled": True,
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        invalid_serializer = AIApplyDraftResponseSerializer(
            data={
                "store_id": 20,
                "final_status": "setup",
                "store_core_applied": True,
                "categories": {"created": [], "skipped": []},
                "products": {"created": [], "skipped": []},
                "draft_deleted": True,
            }
        )
        self.assertFalse(invalid_serializer.is_valid())
        self.assertIn("draft_cleanup_scheduled", invalid_serializer.errors)

        invalid_nested_serializer = AIApplyDraftResponseSerializer(
            data={
                "store_id": 20,
                "final_status": "setup",
                "store_core_applied": True,
                "categories": {
                    "created": [],
                    "skipped": [],
                    "extra": [],
                },
                "products": {"created": [], "skipped": []},
                "draft_cleanup_scheduled": True,
            }
        )
        self.assertFalse(invalid_nested_serializer.is_valid())
        self.assertIn("categories", invalid_nested_serializer.errors)

    def test_empty_serializer_accepts_empty_body(self):
        serializer = EmptySerializer(data={})
        self.assertTrue(serializer.is_valid(), serializer.errors)


class AICreationViewsSmokeTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User(
            username="ai_view_user",
            email="ai_view_user@example.com",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101

    @staticmethod
    def _draft_state_payload(store_id: int = 1) -> dict:
        return {
            "store_id": store_id,
            "draft_payload": {"store": {"name": "Draft Store"}},
            "draft_metadata": {"status": "draft_ready"},
        }

    def test_start_view_success_returns_201(self):
        view = AIStartDraftAPIView.as_view()
        request = self.factory.post(
            "/api/ai/stores/draft/start/",
            {"name": "My Store", "user_store_description": "Great store idea"},
            format="json",
        )
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.create_draft_store_for_ai_flow",
            return_value=SimpleNamespace(id=99),
        ) as mock_create_store, patch(
            "AI_Store_Creation_Service.views.generate_initial_store_draft"
        ) as mock_generate, patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            return_value=self._draft_state_payload(store_id=99),
        ) as mock_get_current:
            response = view(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["store_id"], 99)
        mock_create_store.assert_called_once()
        mock_generate.assert_called_once()
        mock_get_current.assert_called_once()

    def test_current_draft_view_success_returns_200(self):
        view = AICurrentDraftAPIView.as_view()
        request = self.factory.get("/api/ai/stores/7/draft/")
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            return_value=self._draft_state_payload(store_id=7),
        ) as mock_get_current:
            response = view(request, store_id=7)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_id"], 7)
        mock_get_current.assert_called_once()

    def test_clarification_view_success_returns_200(self):
        view = AIClarificationAPIView.as_view()
        request = self.factory.post(
            "/api/ai/stores/11/draft/clarify/",
            {"clarification_answers": "target audience is young adults"},
            format="json",
        )
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.process_clarification_round"
        ) as mock_process, patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            return_value=self._draft_state_payload(store_id=11),
        ) as mock_get_current:
            response = view(request, store_id=11)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_id"], 11)
        mock_process.assert_called_once()
        mock_get_current.assert_called_once()

    def test_regenerate_view_success_returns_200(self):
        view = AIRegenerateDraftAPIView.as_view()
        request = self.factory.post("/api/ai/stores/12/draft/regenerate/", {}, format="json")
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.regenerate_store_draft"
        ) as mock_regenerate, patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            return_value=self._draft_state_payload(store_id=12),
        ) as mock_get_current:
            response = view(request, store_id=12)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_id"], 12)
        mock_regenerate.assert_called_once()
        mock_get_current.assert_called_once()

    def test_regenerate_section_view_success_returns_200(self):
        view = AIRegenerateSectionAPIView.as_view()
        request = self.factory.post(
            "/api/ai/stores/13/draft/regenerate-section/",
            {"target_section": "theme"},
            format="json",
        )
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.regenerate_store_draft_section"
        ) as mock_regenerate_section, patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            return_value=self._draft_state_payload(store_id=13),
        ) as mock_get_current:
            response = view(request, store_id=13)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_id"], 13)
        mock_regenerate_section.assert_called_once()
        mock_get_current.assert_called_once()

    def test_apply_view_success_returns_200(self):
        view = AIApplyDraftAPIView.as_view()
        request = self.factory.post("/api/ai/stores/14/draft/apply/", {}, format="json")
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.apply_current_ai_draft_to_store",
            return_value={
                "store_id": 14,
                "final_status": "setup",
                "store_core_applied": True,
                "categories": {"created": ["Clothes"], "skipped": []},
                "products": {"created": ["TS-001"], "skipped": []},
                "draft_cleanup_scheduled": True,
            },
        ) as mock_apply:
            response = view(request, store_id=14)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["store_id"], 14)
        mock_apply.assert_called_once()

    def test_error_mapping_not_found_returns_404(self):
        view = AICurrentDraftAPIView.as_view()
        request = self.factory.get("/api/ai/stores/404/draft/")
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.get_current_ai_draft",
            side_effect=ValidationError("No temporary AI draft found for this store"),
        ):
            response = view(request, store_id=404)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "No temporary AI draft found for this store")

    def test_error_mapping_bad_request_returns_400(self):
        view = AIApplyDraftAPIView.as_view()
        request = self.factory.post("/api/ai/stores/17/draft/apply/", {}, format="json")
        request.tenant_id = 101
        force_authenticate(request, user=self.user)

        with patch(
            "AI_Store_Creation_Service.views.apply_current_ai_draft_to_store",
            side_effect=ValidationError("Current workflow state is not draft_ready"),
        ):
            response = view(request, store_id=17)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Current workflow state is not draft_ready")


class AICreationURLsTests(SimpleTestCase):
    def test_reverse_ai_routes(self):
        self.assertEqual(
            reverse("ai_store_creation:start-draft"),
            "/api/ai/stores/draft/start/",
        )
        self.assertEqual(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": 1}),
            "/api/ai/stores/1/draft/",
        )
        self.assertEqual(
            reverse("ai_store_creation:clarify-draft", kwargs={"store_id": 2}),
            "/api/ai/stores/2/draft/clarify/",
        )
        self.assertEqual(
            reverse("ai_store_creation:regenerate-draft", kwargs={"store_id": 3}),
            "/api/ai/stores/3/draft/regenerate/",
        )
        self.assertEqual(
            reverse("ai_store_creation:regenerate-draft-section", kwargs={"store_id": 4}),
            "/api/ai/stores/4/draft/regenerate-section/",
        )
        self.assertEqual(
            reverse("ai_store_creation:apply-draft", kwargs={"store_id": 5}),
            "/api/ai/stores/5/draft/apply/",
        )

    def test_resolve_ai_routes(self):
        self.assertIs(
            resolve("/api/ai/stores/draft/start/").func.view_class,
            AIStartDraftAPIView,
        )
        self.assertIs(
            resolve("/api/ai/stores/1/draft/").func.view_class,
            AICurrentDraftAPIView,
        )
        self.assertIs(
            resolve("/api/ai/stores/2/draft/clarify/").func.view_class,
            AIClarificationAPIView,
        )
        self.assertIs(
            resolve("/api/ai/stores/3/draft/regenerate/").func.view_class,
            AIRegenerateDraftAPIView,
        )
        self.assertIs(
            resolve("/api/ai/stores/4/draft/regenerate-section/").func.view_class,
            AIRegenerateSectionAPIView,
        )
        self.assertIs(
            resolve("/api/ai/stores/5/draft/apply/").func.view_class,
            AIApplyDraftAPIView,
        )
