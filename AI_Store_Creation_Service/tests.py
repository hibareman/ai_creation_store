import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store
from themes.models import StoreThemeConfig, ThemeTemplate

from .draft_store import get_ai_draft, get_ai_draft_meta, save_ai_draft, save_ai_draft_meta
from .models import AIStoreAuditLog
from .prompts import build_clarify_store_draft_messages, build_generate_store_draft_messages
from .services import (
    apply_current_ai_draft_categories,
    apply_current_ai_draft_products,
    apply_current_ai_draft_store_core,
    apply_current_ai_draft_to_store,
    create_draft_store_for_ai_flow,
    derive_store_name_from_description,
    generate_initial_store_draft,
    get_current_ai_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
    start_ai_draft_workflow,
)
from .validators import build_ai_fallback_payload

User = get_user_model()


class AIWorkflowBaseMixin:
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
            "store_settings": {
                "currency": "USD",
                "language": "en",
                "timezone": "UTC",
            },
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


class AICreationServicesTests(AIWorkflowBaseMixin, TestCase):
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
        save_ai_draft(store.id, current_draft or self._valid_full_draft_payload())
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
                "clarification_history": clarification_history or [],
            },
        )

    def _prepare_draft_ready_state(
        self,
        store: Store,
        *,
        current_draft: dict | None = None,
        original_description: str = "Original store description",
        clarification_history: list[dict] | None = None,
        latest_clarification_input: str = "Prefer minimal style",
        clarification_round_count: int = 1,
    ):
        save_ai_draft(store.id, current_draft or self._valid_full_draft_payload())
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
                "clarification_history": clarification_history or [],
            },
        )

    def test_create_draft_store_success(self):
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
            create_draft_store_for_ai_flow(user=AnonymousUser(), tenant_id=101, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=None, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=999, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=101, name="   ")

    def test_derive_store_name_extracts_explicit_name(self):
        derived = derive_store_name_from_description(
            'Please create a new store, store name is "Noor Beauty".'
        )
        self.assertEqual(derived, "Noor Beauty")

    def test_derive_store_name_returns_safe_non_empty_fallback(self):
        derived = derive_store_name_from_description("This is a very vague description.")
        self.assertIsInstance(derived, str)
        self.assertTrue(derived.strip())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_ai_draft_workflow_creates_store_with_locally_derived_name(self, mock_get_provider):
        self._seed_templates()
        payload = self._clarification_payload()
        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        draft_state = start_ai_draft_workflow(
            user=self.user,
            tenant_id=101,
            user_store_description="I want to build an electronics and gadgets store.",
        )

        self.assertEqual(set(draft_state.keys()), {"store_id", "draft_payload", "draft_metadata"})
        created_store = Store.objects.get(id=draft_state["store_id"])
        self.assertTrue(created_store.name.strip())
        self.assertEqual(created_store.owner_id, self.user.id)
        self.assertEqual(created_store.tenant_id, 101)
        self.assertEqual(created_store.status, "draft")

    def test_clarify_prompt_contract_requires_full_draft_when_information_is_sufficient(self):
        messages = build_clarify_store_draft_messages(
            tenant_id=101,
            store_id=1,
            current_draft=self._clarification_payload(),
            prompt="Store type is fashion and all details are clear",
            context={"original_store_description": "Fashion store"},
        )
        system_prompt = messages[0]["content"]
        self.assertIn("return a complete valid draft payload now", system_prompt)
        self.assertIn('"clarification_needed": false', system_prompt)
        self.assertIn('"clarification_questions": []', system_prompt)

    def test_full_generation_prompt_contract_mentions_targeted_reliability_constraints(self):
        messages = build_generate_store_draft_messages(
            tenant_id=101,
            store_id=1,
            user_store_description="Build me a beauty store",
            available_theme_templates=["Modern", "Classic"],
        )
        system_prompt = messages[0]["content"]
        self.assertIn("Generate between 2 and 4 products.", system_prompt)
        self.assertIn("Never return more than 4 products.", system_prompt)
        self.assertIn("`theme_template`", system_prompt)
        self.assertIn("`primary_color`", system_prompt)
        self.assertIn("non-empty string", system_prompt)
        self.assertIn("no blank strings, nulls, or empty values", system_prompt)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_success_full_draft(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_canonicalizes_theme_template_name(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "  modern  "

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["theme"]["theme_template"], "Modern")
        self.assertEqual(get_ai_draft(store.id)["theme"]["theme_template"], "Modern")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_normalizes_missing_product_image_url(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0].pop("image_url", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["products"][0]["image_url"], "")
        self.assertEqual(get_ai_draft_meta(store.id)["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_normalizes_null_product_image_url(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0]["image_url"] = None

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["products"][0]["image_url"], "")
        self.assertEqual(get_ai_draft_meta(store.id)["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_keeps_valid_product_image_url_unchanged(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0]["image_url"] = "https://cdn.example.com/p-1.png"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["products"][0]["image_url"], "https://cdn.example.com/p-1.png")
        self.assertEqual(result["products"][1]["image_url"], "")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_still_fails_for_core_invalid_product_payload(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0].pop("sku", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result, build_ai_fallback_payload())
        meta = get_ai_draft_meta(store.id)
        self.assertTrue(meta["is_fallback"])
        self.assertIn("missing required field 'sku'", meta["reason"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_trims_products_to_allowed_max(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"].extend(
            [
                {
                    "name": "Hat",
                    "description": "Sport hat",
                    "price": 15,
                    "sku": "HT-001",
                    "category_name": "Clothes",
                    "stock_quantity": 7,
                    "image_url": "",
                },
                {
                    "name": "Socks",
                    "description": "Daily socks",
                    "price": 8,
                    "sku": "SK-001",
                    "category_name": "Clothes",
                    "stock_quantity": 20,
                    "image_url": "",
                },
                {
                    "name": "Backpack",
                    "description": "Travel backpack",
                    "price": 42,
                    "sku": "BP-001",
                    "category_name": "Shoes",
                    "stock_quantity": 4,
                    "image_url": "",
                },
            ]
        )

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(len(result["products"]), 4)
        self.assertEqual(result["products"][-1]["sku"], "SK-001")
        self.assertEqual(get_ai_draft_meta(store.id)["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_cleans_clarification_options_before_validation(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._clarification_payload()
        payload["clarification_questions"][0]["options"] = ["Fashion", "", None, "  ", "Electronics"]

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertTrue(result["clarification_needed"])
        self.assertEqual(
            result["clarification_questions"][0]["options"],
            ["Fashion", "Electronics"],
        )
        self.assertEqual(get_ai_draft_meta(store.id)["status"], "needs_clarification")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_resolves_theme_template_from_style_hint(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "   "
        payload["theme"]["style"] = " modern "

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["theme"]["theme_template"], "Modern")
        self.assertEqual(get_ai_draft_meta(store.id)["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_unresolved_theme_template_still_fails(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "   "
        payload["theme"]["style"] = "futuristic-neon"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result, build_ai_fallback_payload())
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertTrue(meta["is_fallback"])
        self.assertIn("theme_template", meta["reason"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_keeps_core_validation_strict_for_invalid_categories(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Only One Category"}]
        payload["products"][0]["category_name"] = "Only One Category"
        payload["products"][1]["category_name"] = "Only One Category"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result, build_ai_fallback_payload())
        meta = get_ai_draft_meta(store.id)
        self.assertTrue(meta["is_fallback"])
        self.assertIn("Categories list must contain between 2 and 5 items.", meta["reason"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_success_clarification_mode(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._clarification_payload()

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_clarification_payload_with_missing_structural_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = {
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertEqual(result["clarification_needed"], True)
        self.assertIn("store", result)
        self.assertIn("store_settings", result)
        self.assertIn("theme", result)
        self.assertIn("categories", result)
        self.assertIn("products", result)
        self.assertEqual(result["store"], {})
        self.assertEqual(result["categories"], [])
        self.assertEqual(get_ai_draft(store.id), result)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_clarification_questions_with_extra_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = {
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                    "hint": "Choose one",
                    "priority": 1,
                }
            ],
        }

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertTrue(result["clarification_needed"])
        self.assertEqual(result["clarification_questions"][0]["question_key"], "store_type")
        self.assertIn("hint", result["clarification_questions"][0])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_full_payload_without_clarification_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload.pop("clarification_needed", None)
        payload.pop("clarification_questions", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store",
        )

        self.assertEqual(result["clarification_needed"], False)
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(result["store"]["name"], "My Store")

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_on_provider_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        mock_get_provider.return_value.generate_store_draft.side_effect = RuntimeError("provider timeout")

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any description",
        )

        fallback = build_ai_fallback_payload()
        self.assertEqual(result, fallback)
        self.assertEqual(get_ai_draft(store.id), fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertTrue(meta["is_fallback"])

    def test_get_current_ai_draft_success(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        metadata = {
            "status": "draft_ready",
            "current_step": "setting_up_store_configuration",
            "mode": "draft_ready",
            "original_user_store_description": "Sportswear store",
        }
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(store.id, metadata)

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(result["draft_metadata"], metadata)

    def test_get_current_ai_draft_rebuilds_missing_metadata_when_draft_exists(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, payload)

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(result["draft_metadata"]["status"], "draft_ready")
        self.assertEqual(result["draft_metadata"]["mode"], "draft_ready")
        self.assertTrue(result["draft_metadata"]["original_user_store_description"].strip())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_stays_in_clarification(self, mock_get_provider):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)

        next_payload = self._clarification_payload()
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(next_payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        self.assertEqual(result, next_payload)
        self.assertEqual(get_ai_draft(store.id), next_payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["clarification_round_count"], 1)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_rebuilds_missing_metadata_when_draft_exists(
        self, mock_get_provider
    ):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(
            self._clarification_payload()
        )

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        self.assertTrue(result["clarification_needed"])
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "needs_clarification")
        self.assertEqual(meta["mode"], "clarification")
        self.assertTrue(meta["original_user_store_description"].strip())
        self.assertEqual(meta["clarification_round_count"], 1)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_provider_failure_keeps_round_tracking_consistent(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0)
        mock_get_provider.return_value.clarify_store_draft.side_effect = RuntimeError("provider timeout")

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        fallback = build_ai_fallback_payload()
        self.assertEqual(result, fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["clarification_round_count"], 1)
        self.assertEqual(meta["clarification_history"][0]["round"], 1)
        self.assertEqual(meta["clarification_round_count"], meta["clarification_history"][-1]["round"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_transitions_to_draft_ready(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=0)

        payload = self._valid_full_draft_payload()
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Target audience: young adults",
        )

        self.assertEqual(result, payload)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertEqual(meta["clarification_round_count"], 1)

    def test_process_clarification_round_enforces_round_limit(self):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=3)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        fallback = build_ai_fallback_payload()
        self.assertEqual(result, fallback)
        self.assertEqual(get_ai_draft(store.id), fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_success(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(store, current_draft=self._clarification_payload())

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Regenerated Store"
        mock_get_provider.return_value.regenerate_store_draft.return_value = self._as_provider_response(payload)

        result = regenerate_store_draft(store.id, self.user, 101)

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_success_theme(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=base_payload)

        replacement_theme = {
            "theme_template": "Classic",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": replacement_theme}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="theme",
        )

        self.assertEqual(result["theme"], replacement_theme)
        self.assertEqual(result["categories"], base_payload["categories"])
        self.assertEqual(result["products"], base_payload["products"])

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["last_partial_regeneration_target_section"], "theme")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_rebuilds_missing_metadata_when_draft_exists(
        self, mock_get_provider
    ):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, base_payload)

        replacement_theme = {
            "theme_template": " classic ",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": replacement_theme}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="theme",
        )

        self.assertEqual(result["theme"]["theme_template"], "Classic")
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertTrue(meta["original_user_store_description"].strip())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_failure_keeps_draft_unchanged(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=base_payload)
        before = get_ai_draft(store.id)

        mock_get_provider.return_value.regenerate_store_draft_section.side_effect = RuntimeError("provider timeout")

        with self.assertRaises(ValidationError):
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="theme",
            )

        self.assertEqual(get_ai_draft(store.id), before)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], "draft_ready")
        self.assertIn("provider timeout", meta["last_partial_regeneration_error"])

    def test_apply_current_ai_draft_store_core_success(self):
        store = self._create_store()
        self._seed_templates()

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Applied Store Name"
        payload["store"]["description"] = "Applied description"
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_store_core(store.id, self.user, 101)

        store.refresh_from_db()
        self.assertEqual(store.name, "Applied Store Name")
        self.assertEqual(store.description, "Applied description")
        self.assertEqual(store.status, "draft")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        self.assertEqual(result["draft_status"], "draft_ready")

    def test_apply_current_ai_draft_categories_success(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_categories(store.id, self.user, 101)

        self.assertEqual(Category.objects.filter(store=store).count(), 2)
        self.assertEqual(result["created_categories"], ["Clothes", "Shoes"])
        self.assertEqual(result["skipped_categories"], [])

    def test_apply_current_ai_draft_products_success(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-NEW-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][0]["image_url"] = "https://img.example.com/ts-001.jpg"
        payload["products"][1]["sku"] = "SN-NEW-001"
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][1]["image_url"] = ""
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_products(store.id, self.user, 101)

        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 1)
        self.assertEqual(result["created_products"], ["TS-NEW-001", "SN-NEW-001"])
        self.assertEqual(result["skipped_products"], [])

    def test_apply_current_ai_draft_to_store_success(self):
        store = self._create_store()
        self._seed_templates()

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Final Applied Store"
        payload["store"]["description"] = "Final applied description"
        payload["products"][0]["sku"] = "AP-TS-001"
        payload["products"][1]["sku"] = "AP-SN-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][0]["image_url"] = "https://img.example.com/ap-ts-001.jpg"
        payload["products"][1]["image_url"] = ""
        self._prepare_draft_ready_state(store, current_draft=payload)

        with self.captureOnCommitCallbacks(execute=True):
            result = apply_current_ai_draft_to_store(store.id, self.user, 101)

        store.refresh_from_db()
        self.assertEqual(store.status, "setup")
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


class AICreationApiTests(AIWorkflowBaseMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="ai_api_owner",
            email="ai_api_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

        self.other_owner_same_tenant = User.objects.create_user(
            username="ai_api_other_owner",
            email="ai_api_other_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.other_owner_same_tenant.is_active = True
        self.other_owner_same_tenant.tenant_id = 101
        self.other_owner_same_tenant.save(update_fields=["is_active", "tenant_id"])

        self._seed_templates()
        self._authenticate(self.user)

    def _seed_templates(self):
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    def _authenticate(self, user):
        response = self.client.post(
            "/api/auth/login/",
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")

    @staticmethod
    def _payload(response):
        return response.json()

    def _create_store(self, owner=None, tenant_id=None) -> Store:
        owner = owner or self.user
        tenant_id = tenant_id if tenant_id is not None else owner.tenant_id
        return Store.objects.create(
            owner=owner,
            tenant_id=tenant_id,
            name="Endpoint Draft Store",
            description="",
            status="draft",
        )

    def test_start_endpoint_happy_path(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": "A modern sportswear store",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(body["draft_payload"], payload)
        self.assertEqual(body["draft_metadata"]["status"], "draft_ready")

        created_store = Store.objects.get(id=body["store_id"])
        self.assertTrue(created_store.name.strip())

    def test_start_endpoint_accepts_deprecated_user_store_description(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_store_description": "A modern sportswear store",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {"store_id", "draft_payload", "draft_metadata"})

    def test_start_endpoint_prefers_user_description_when_both_fields_exist(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": 'store name is "Priority Name"',
                    "user_store_description": 'store name is "Deprecated Name"',
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        store_id = self._payload(response)["store_id"]
        created_store = Store.objects.get(id=store_id)
        self.assertEqual(created_store.name, "Priority Name")

    def test_current_draft_endpoint_happy_path(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        metadata = {
            "status": "draft_ready",
            "current_step": "setting_up_store_configuration",
            "mode": "draft_ready",
            "original_user_store_description": "Sportswear store",
        }
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(store.id, metadata)

        response = self.client.get(reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id}))

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["store_id"], store.id)
        self.assertEqual(body["draft_payload"], payload)
        self.assertEqual(body["draft_metadata"], metadata)

    def test_clarification_endpoint_happy_path(self):
        start_payload = self._clarification_payload()
        final_payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(start_payload)

            start_response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": "I need help defining my store",
                },
                format="json",
            )
            self.assertEqual(start_response.status_code, 201)
            store_id = start_response.json()["store_id"]

            mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(final_payload)
            response = self.client.post(
                reverse("ai_store_creation:clarify-draft", kwargs={"store_id": store_id}),
                {"clarification_answers": {"store_type": "Fashion"}},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["store_id"], store_id)
        self.assertEqual(body["draft_payload"], final_payload)
        self.assertEqual(body["draft_metadata"]["status"], "draft_ready")

    def test_regenerate_endpoint_happy_path(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Target audience: adults",
                "clarification_history": [{"round": 1, "clarification_input": "Target audience: adults"}],
            },
        )

        regenerated = self._valid_full_draft_payload()
        regenerated["store"]["name"] = "Regenerated Store Name"

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.regenerate_store_draft.return_value = self._as_provider_response(regenerated)
            response = self.client.post(
                reverse("ai_store_creation:regenerate-draft", kwargs={"store_id": store.id}),
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["draft_payload"]["store"]["name"], "Regenerated Store Name")
        self.assertEqual(body["draft_metadata"]["status"], "draft_ready")

    def test_regenerate_section_endpoint_happy_path(self):
        store = self._create_store()
        base_payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, base_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Prefer modern style",
                "clarification_history": [{"round": 1, "clarification_input": "Prefer modern style"}],
            },
        )

        replacement_theme = {
            "theme_template": "Classic",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
                {"theme": replacement_theme}
            )
            response = self.client.post(
                reverse("ai_store_creation:regenerate-draft-section", kwargs={"store_id": store.id}),
                {"target_section": "theme"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["draft_payload"]["theme"], replacement_theme)
        self.assertEqual(body["draft_payload"]["categories"], base_payload["categories"])
        self.assertEqual(body["draft_payload"]["products"], base_payload["products"])
        self.assertEqual(body["draft_metadata"]["status"], "draft_ready")

    def test_apply_endpoint_happy_path(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Final Applied Store"
        payload["store"]["description"] = "Final applied description"
        payload["products"][0]["sku"] = "AP-TS-001"
        payload["products"][1]["sku"] = "AP-SN-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][0]["image_url"] = "https://img.example.com/ap-ts-001.jpg"
        payload["products"][1]["image_url"] = ""
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Prefer modern style",
                "clarification_history": [{"round": 1, "clarification_input": "Prefer modern style"}],
            },
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("ai_store_creation:apply-draft", kwargs={"store_id": store.id}),
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {
            "store_id",
            "final_status",
            "store_core_applied",
            "categories",
            "products",
            "draft_cleanup_scheduled",
        })
        self.assertEqual(body["final_status"], "setup")
        self.assertTrue(body["draft_cleanup_scheduled"])

    def test_start_endpoint_rejects_unauthenticated(self):
        self.client.credentials()
        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Desc"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_start_endpoint_rejects_blank_description(self):
        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "   ", "user_store_description": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_current_draft_rejects_wrong_owner_access(self):
        foreign_store = self._create_store(owner=self.other_owner_same_tenant, tenant_id=101)
        save_ai_draft(foreign_store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            foreign_store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Desc",
            },
        )

        response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": foreign_store.id})
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_current_draft_returns_404_when_missing(self):
        store = self._create_store()
        response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id})
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_clarification_rejects_blank_answers(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 0,
                "original_user_store_description": "Original store description",
            },
        )

        response = self.client.post(
            reverse("ai_store_creation:clarify-draft", kwargs={"store_id": store.id}),
            {"clarification_answers": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_regenerate_section_rejects_invalid_target_section(self):
        store = self._create_store()
        save_ai_draft(store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
            },
        )

        response = self.client.post(
            reverse("ai_store_creation:regenerate-draft-section", kwargs={"store_id": store.id}),
            {"target_section": "store"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_endpoint_returns_safe_fallback_when_provider_fails(self, mock_get_provider):
        mock_get_provider.return_value.generate_store_draft.side_effect = RuntimeError("provider timeout")

        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Desc"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["draft_metadata"]["status"], "needs_clarification")
        self.assertTrue(body["draft_metadata"]["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_endpoint_repeated_vague_descriptions_create_valid_unique_stores(
        self,
        mock_get_provider,
    ):
        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            self._clarification_payload()
        )

        first_response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Store please"},
            format="json",
        )
        second_response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Store please"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        first_store = Store.objects.get(id=self._payload(first_response)["store_id"])
        second_store = Store.objects.get(id=self._payload(second_response)["store_id"])
        self.assertTrue(first_store.name.strip())
        self.assertTrue(second_store.name.strip())
        self.assertNotEqual(first_store.slug, second_store.slug)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_endpoint_returns_safe_fallback_when_provider_fails(self, mock_get_provider):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
            },
        )

        mock_get_provider.return_value.regenerate_store_draft.side_effect = RuntimeError("provider timeout")

        response = self.client.post(
            reverse("ai_store_creation:regenerate-draft", kwargs={"store_id": store.id}),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["draft_metadata"]["status"], "needs_clarification")
        self.assertTrue(body["draft_metadata"]["is_fallback"])
