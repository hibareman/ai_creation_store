"""Focused contract tests for the draft-only ``ai_analysis`` field."""

from copy import deepcopy
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from .agentic.repairing import _choose_repair_strategy, repair_draft_payload
from .agentic_production_services import _project_public_draft_payload
from .exceptions import AIDraftSchemaValidationError
from .normalization import _apply_targeted_prevalidation_repairs
from .validators import (
    validate_ai_analysis,
    validate_basic_draft_schema,
    validate_regenerated_draft_schema,
)
from .workflow_services import (
    _extract_partial_section_replacement,
    _validate_partial_regeneration_candidate,
)
from .prompts import build_regenerate_store_draft_section_messages


class AIAnalysisFieldContractTests(SimpleTestCase):
    def test_analysis_is_normalized_to_one_continuous_text_value(self):
        value = "  فهمت المتجر.\n\n أوصي بتطوير المحتوى.  "

        self.assertEqual(
            validate_ai_analysis(value),
            "فهمت المتجر. أوصي بتطوير المحتوى.",
        )
        self.assertEqual(
            _apply_targeted_prevalidation_repairs({"ai_analysis": value})[
                "ai_analysis"
            ],
            "فهمت المتجر. أوصي بتطوير المحتوى.",
        )

    def test_legacy_or_clarification_payload_gets_safe_empty_default(self):
        payload = validate_basic_draft_schema(
            {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": [{"question_key": "store_type"}],
            }
        )

        self.assertEqual(payload["ai_analysis"], "")

    def test_ready_analysis_rejects_empty_text(self):
        with self.assertRaises(AIDraftSchemaValidationError):
            validate_ai_analysis("   ")

    def test_full_regeneration_contract_requires_analysis(self):
        payload = {
            "regeneration_summary": {
                "title": "بديل جديد",
                "message": "سطر أول\nسطر ثان\nسطر ثالث",
                "highlights": ["أ", "ب", "ج"],
            },
            "ai_analysis": "تحليل متوافق مع المسودة الجديدة.",
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": False,
            "clarification_questions": [],
        }

        validated = validate_regenerated_draft_schema(payload)
        self.assertEqual(
            validated["ai_analysis"],
            "تحليل متوافق مع المسودة الجديدة.",
        )

    def test_partial_regeneration_returns_section_and_updated_analysis(self):
        replacement = _extract_partial_section_replacement(
            {
                "theme": {"theme_template": "Minimal"},
                "ai_analysis": "تحليل محدث بعد تغيير الثيم.",
            },
            "theme",
        )

        self.assertEqual(replacement["theme"]["theme_template"], "Minimal")
        self.assertEqual(
            replacement["ai_analysis"],
            "تحليل محدث بعد تغيير الثيم.",
        )

    def test_missing_analysis_routes_to_targeted_repair(self):
        strategy = _choose_repair_strategy(
            [
                {
                    "path": "ai_analysis",
                    "code": "ai_analysis_invalid",
                    "message": "ai_analysis is missing.",
                    "repairable": True,
                }
            ]
        )

        self.assertEqual(strategy, ("section", "ai_analysis"))

    def test_public_projection_exposes_normalized_analysis(self):
        projected = _project_public_draft_payload(
            {
                "store": {"name": "متجر", "description": "وصف"},
                "store_settings": {"currency": "SAR", "language": "ar", "timezone": "Asia/Riyadh"},
                "theme": {"theme_template": "Minimal"},
                "categories": [],
                "products": [],
                "ai_analysis": "  تحليل أول.\n\nتحليل ثان.  ",
                "clarification_needed": False,
                "clarification_questions": [],
            }
        )

        self.assertEqual(projected["ai_analysis"], "تحليل أول. تحليل ثان.")

    def test_internal_repair_uses_section_only_contract(self):
        messages = build_regenerate_store_draft_section_messages(
            tenant_id=1,
            store_id=2,
            target_section="theme",
            original_store_description="متجر تجريبي متكامل",
            current_draft={"theme": {"theme_template": "Minimal"}},
            clarification_context={
                "operation": "agentic_validation_repair",
                "validation_errors": [
                    {
                        "path": "theme.theme_template",
                        "code": "theme_template_unavailable",
                        "message": "Template is unavailable.",
                        "repairable": True,
                    }
                ],
            },
            available_theme_templates=["Minimal"],
        )

        system_prompt = messages[0]["content"]
        self.assertIn("مفتاحًا علويًا واحدًا فقط", system_prompt)
        self.assertIn("لا تُرجع ai_analysis مع أي قسم آخر", system_prompt)



class PartialRegenerationAndAnalysisRepairTests(SimpleTestCase):
    def _ready_draft(self):
        return {
            "store": {"name": "قهوة بيتك", "description": "متجر قهوة مختصة متكامل."},
            "store_settings": {
                "currency": "SAR",
                "language": "ar",
                "timezone": "Asia/Riyadh",
            },
            "theme": {
                "theme_template": "Minimal",
                "primary_color": "#6B4F4F",
                "secondary_color": "#D8C3A5",
                "font_family": "Cairo",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [
                {"name": "حبوب القهوة"},
                {"name": "أدوات التحضير"},
                {"name": "الإكسسوارات"},
            ],
            "products": [
                {
                    "name": f"منتج {index}",
                    "description": "وصف منتج واضح ومناسب للمتجر.",
                    "price": 20 + index,
                    "sku": f"SKU-{index}",
                    "category_name": ["حبوب القهوة", "أدوات التحضير", "الإكسسوارات"][index % 3],
                    "stock_quantity": 10,
                    "image_url": "",
                }
                for index in range(4)
            ],
            "ai_analysis": "تحليل المسودة الأصلية قبل إعادة التوليد الجزئي.",
            "clarification_needed": False,
            "clarification_questions": [],
        }

    def test_theme_partial_contract_requires_theme_and_fresh_analysis_only(self):
        replacement = _extract_partial_section_replacement(
            {
                "theme": {"theme_template": "Modern"},
                "ai_analysis": "تحليل جديد يشرح الهوية البصرية الحديثة.",
            },
            "theme",
        )
        self.assertEqual(set(replacement), {"theme", "ai_analysis"})

    def test_products_partial_contract_requires_products_and_fresh_analysis_only(self):
        replacement = _extract_partial_section_replacement(
            {
                "products": [],
                "ai_analysis": "تحليل جديد يشرح استراتيجية المنتجات البديلة.",
            },
            "products",
        )
        self.assertEqual(set(replacement), {"products", "ai_analysis"})

    def test_categories_partial_contract_requires_categories_products_and_analysis(self):
        replacement = _extract_partial_section_replacement(
            {
                "categories": [],
                "products": [],
                "ai_analysis": "تحليل جديد يشرح بنية الكتالوج البديلة.",
            },
            "categories",
        )
        self.assertEqual(
            set(replacement),
            {"categories", "products", "ai_analysis"},
        )

    def test_partial_candidate_rejects_unchanged_analysis(self):
        current = self._ready_draft()
        candidate = deepcopy(current)
        candidate["theme"] = {
            **candidate["theme"],
            "primary_color": "#112233",
        }
        with self.assertRaises(AIDraftSchemaValidationError):
            _validate_partial_regeneration_candidate(
                candidate,
                previous_draft=current,
                available_theme_templates=["Minimal"],
            )

    def test_partial_candidate_accepts_fresh_analysis_and_preserves_other_sections(self):
        current = self._ready_draft()
        candidate = deepcopy(current)
        candidate["theme"] = {
            **candidate["theme"],
            "primary_color": "#112233",
        }
        candidate["ai_analysis"] = (
            "تحليل محدث يوضح أثر اللون الجديد مع الحفاظ على الجمهور والمنتجات."
        )
        validated = _validate_partial_regeneration_candidate(
            candidate,
            previous_draft=current,
            available_theme_templates=["Minimal"],
        )
        self.assertEqual(validated["store"], current["store"])
        self.assertEqual(validated["categories"], current["categories"])
        self.assertEqual(validated["products"], current["products"])
        self.assertNotEqual(validated["ai_analysis"], current["ai_analysis"])

    def test_products_candidate_updates_products_and_analysis_only(self):
        current = self._ready_draft()
        candidate = deepcopy(current)
        candidate["products"] = [
            {
                "name": f"منتج بديل {index}",
                "description": "وصف بديل واضح ومناسب لفئة المنتج الحالية.",
                "price": 40 + index,
                "sku": f"ALT-{index}",
                "category_name": [
                    "حبوب القهوة",
                    "أدوات التحضير",
                    "الإكسسوارات",
                ][index % 3],
                "stock_quantity": 12,
                "image_url": "",
            }
            for index in range(4)
        ]
        candidate["ai_analysis"] = (
            "تحليل محدث يشرح تشكيلة المنتجات البديلة وتوافقها مع الفئات الحالية."
        )
        validated = _validate_partial_regeneration_candidate(
            candidate,
            previous_draft=current,
        )
        self.assertEqual(validated["store"], current["store"])
        self.assertEqual(validated["theme"], current["theme"])
        self.assertEqual(validated["categories"], current["categories"])
        self.assertNotEqual(validated["products"], current["products"])
        self.assertNotEqual(validated["ai_analysis"], current["ai_analysis"])

    def test_categories_candidate_updates_categories_products_and_analysis(self):
        current = self._ready_draft()
        candidate = deepcopy(current)
        candidate["categories"] = [
            {"name": "قهوة التقطير"},
            {"name": "معدات الطحن"},
            {"name": "باقات القهوة"},
        ]
        candidate["products"] = [
            {
                "name": f"عنصر كتالوج {index}",
                "description": "منتج بديل متوافق مع بنية الفئات الجديدة للمتجر.",
                "price": 60 + index,
                "sku": f"CAT-{index}",
                "category_name": [
                    "قهوة التقطير",
                    "معدات الطحن",
                    "باقات القهوة",
                ][index % 3],
                "stock_quantity": 8,
                "image_url": "",
            }
            for index in range(4)
        ]
        candidate["ai_analysis"] = (
            "تحليل محدث يشرح الفئات الجديدة والمنتجات المتوافقة معها تجاريًا."
        )
        validated = _validate_partial_regeneration_candidate(
            candidate,
            previous_draft=current,
        )
        self.assertEqual(validated["store"], current["store"])
        self.assertEqual(validated["theme"], current["theme"])
        self.assertNotEqual(validated["categories"], current["categories"])
        self.assertNotEqual(validated["products"], current["products"])
        self.assertNotEqual(validated["ai_analysis"], current["ai_analysis"])

    def test_user_partial_prompt_has_only_supported_api_targets(self):
        messages = build_regenerate_store_draft_section_messages(
            tenant_id=1,
            store_id=2,
            target_section="products",
            original_store_description="متجر قهوة مختصة متكامل في السعودية",
            current_draft=self._ready_draft(),
        )
        system_prompt = messages[0]["content"]
        self.assertIn("القيم المدعومة في هذا المسار فقط", system_prompt)
        self.assertIn("- theme", system_prompt)
        self.assertIn("- categories", system_prompt)
        self.assertIn("- products", system_prompt)
        self.assertNotIn("- store_settings", system_prompt)
        self.assertNotIn("- ai_analysis (يستخدمه مسار الإصلاح الداخلي فقط)", system_prompt)
        self.assertIn("ولا تنسخه من current_draft", system_prompt)

    def test_missing_ai_analysis_repair_changes_only_ai_analysis(self):
        current = self._ready_draft()
        current.pop("ai_analysis")

        class FakeProvider:
            def regenerate_store_draft_section(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "ai_analysis": (
                                            "تحليل مُصلح يصف المتجر والفئات والمنتجات والثيم الحالي."
                                        )
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

        provider = FakeProvider()
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            repaired = repair_draft_payload(
                store_id=10,
                tenant_id=20,
                user_id=30,
                normalized_description="متجر قهوة مختصة متكامل في السعودية",
                expected_mode="draft_ready",
                current_draft=current,
                validation_errors=[
                    {
                        "path": "ai_analysis",
                        "code": "ai_analysis_invalid",
                        "message": "ai_analysis is missing.",
                        "repairable": True,
                    }
                ],
                available_theme_templates=["Minimal"],
                repair_attempt_count=0,
            )

        for key, value in current.items():
            self.assertEqual(repaired[key], value)
        self.assertEqual(
            repaired["ai_analysis"],
            "تحليل مُصلح يصف المتجر والفئات والمنتجات والثيم الحالي.",
        )
        self.assertEqual(provider.kwargs["target_section"], "ai_analysis")
        self.assertEqual(
            provider.kwargs["clarification_context"]["operation"],
            "agentic_validation_repair",
        )
