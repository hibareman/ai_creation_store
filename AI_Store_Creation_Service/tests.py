import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase

from stores.models import Store
from themes.models import ThemeTemplate

from .draft_store import (
    get_ai_draft,
    get_ai_draft_meta,
    save_ai_draft,
    save_ai_draft_meta,
)
from .services import (
    create_draft_store_for_ai_flow,
    generate_initial_store_draft,
    process_clarification_round,
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

        def test_generate_initial_store_draft_rejects_when_no_theme_templates_exist(
            self,
            mock_get_templates,
        ):
            store = self._create_store()

            with self.assertRaises(ValidationError):
                generate_initial_store_draft(
                    store_id=store.id,
                    user=self.user,
                    tenant_id=101,
                    user_store_description="Any description",
                )       

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
