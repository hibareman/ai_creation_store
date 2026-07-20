from unittest import TestCase
from unittest.mock import patch

from AI_Store_Creation_Service.agentic.generation import (
    validate_personalization_constrained_draft,
)
from AI_Store_Creation_Service.agentic.personalization import (
    CORE_PERSONALIZATION_KEYS,
    build_personalization_understanding,
    select_clarification_question_keys,
)
from AI_Store_Creation_Service.agentic.understanding import (
    validate_semantic_analysis_payload,
)


def _personalization(**overrides):
    values = {key: "" for key in CORE_PERSONALIZATION_KEYS}
    values.update(overrides)
    return values


def _analysis(language="en", personalization=None):
    personalization = personalization or _personalization()
    missing = [key for key, value in personalization.items() if not value]
    return {
        "description_language": language,
        "description_sufficient": not missing,
        "detected_store_domains": ["semantic summary"] if not missing else [],
        "business_summary": "ملخص متجر" if language == "ar" else "Store summary",
        "target_audience": personalization["target_audience"],
        "product_direction": [personalization["product_offering"]] if not missing else [],
        "personalization": personalization,
        "blocking_missing_information": missing,
        "ambiguities": [],
    }


class AISemanticUnderstandingTests(TestCase):
    def test_partial_english_extraction_keeps_missing_fields_empty(self):
        payload = _analysis(
            personalization=_personalization(
                product_offering="handmade candles",
                target_audience="home decor shoppers",
            )
        )
        result = validate_semantic_analysis_payload(payload)
        self.assertEqual(result["personalization"]["product_offering"], "handmade candles")
        self.assertEqual(result["personalization"]["catalog_scope"], "")
        self.assertFalse(result["description_sufficient"])


    def test_sparse_description_can_report_all_unresolved_core_fields(self):
        payload = _analysis(
            personalization=_personalization(
                product_offering="handmade candles",
            )
        )
        result = validate_semantic_analysis_payload(payload)
        self.assertFalse(result["description_sufficient"])
        self.assertEqual(
            result["blocking_missing_information"],
            list(CORE_PERSONALIZATION_KEYS[1:]),
        )

    def test_complete_arabic_extraction_is_accepted(self):
        facts = {key: f"قيمة {index}" for index, key in enumerate(CORE_PERSONALIZATION_KEYS, 1)}
        facts["language_currency"] = "العربية والريال السعودي"
        result = validate_semantic_analysis_payload(_analysis("ar", facts))
        self.assertTrue(result["description_sufficient"])
        self.assertEqual(result["description_language"], "ar")
        self.assertEqual(set(result["personalization"]), set(CORE_PERSONALIZATION_KEYS))

    def test_new_user_answers_override_ai_extracted_description_facts(self):
        result = build_personalization_understanding(
            "description",
            ai_personalization_facts=_personalization(
                product_offering="candles",
                price_positioning="budget",
            ),
            clarification_facts={"price_positioning": "premium"},
            semantic_blocking_missing_information=[],
        )
        self.assertEqual(
            result["effective_personalization_context"]["price_positioning"],
            "premium",
        )

    def test_previously_asked_keys_are_not_repeated(self):
        selected = select_clarification_question_keys(
            description_personalization_facts={"product_offering": "coffee"},
            clarification_facts={},
            missing_core_personalization_keys=list(CORE_PERSONALIZATION_KEYS[1:]),
            ambiguous_personalization_keys=[],
            additional_blocking_missing_information=[],
            clarification_round_count=1,
            clarification_history=[{
                "round_number": 1,
                "questions": [{"question_key": "catalog_scope"}],
                "answers": [],
                "resolved_facts": {},
            }],
        )
        self.assertNotIn("catalog_scope", selected)

    @patch("AI_Store_Creation_Service.agentic.generation.validate_store_blueprint")
    def test_backend_does_not_reject_by_fixed_product_domain_words(self, validate_blueprint):
        validate_blueprint.return_value = {}
        context = {key: f"value-{key}" for key in CORE_PERSONALIZATION_KEYS}
        validate_personalization_constrained_draft(
            {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [{"name": "Unexpected wording"}],
                "products": [{"name": "Semantically valid but dictionary-unknown item"}],
            },
            blueprint={"available_theme_templates": ["Default"]},
            effective_personalization_context=context,
        )
        validate_blueprint.assert_called_once()
