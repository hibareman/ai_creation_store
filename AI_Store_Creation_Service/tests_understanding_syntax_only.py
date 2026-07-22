from copy import deepcopy
from django.test import SimpleTestCase

from .agentic.personalization import CORE_PERSONALIZATION_KEYS
from .agentic.understanding import (
    AIUnderstandingValidationError,
    validate_semantic_analysis_payload,
)


class UnderstandSyntaxOnlyProjectionTests(SimpleTestCase):
    def test_extra_keys_do_not_reject_valid_json(self):
        result = validate_semantic_analysis_payload({
            "description_language": "en",
            "unexpected_model_note": {"anything": True},
            "personalization": {"product_offering": "Board games"},
        })
        self.assertEqual(result["personalization"]["product_offering"], "Board games")

    def test_missing_fields_receive_structural_defaults(self):
        result = validate_semantic_analysis_payload({})
        self.assertEqual(set(result["personalization"]), set(CORE_PERSONALIZATION_KEYS))
        self.assertEqual(result["missing_information"], [])
        self.assertFalse(result["description_sufficient"])

    def test_partial_and_imperfect_types_do_not_reject_entire_result(self):
        result = validate_semantic_analysis_payload({
            "description_language": 17,
            "description_sufficient": "yes",
            "detected_store_domains": "games",
            "product_direction": ["tabletop", 8, None],
            "personalization": {
                "product_offering": "ألعاب لوحية",
                "catalog_scope": ["focused"],
                "unknown_fact": "ignored",
            },
            "confidence_score": "0.82",
        })
        self.assertEqual(result["description_language"], "unknown")
        self.assertFalse(result["description_sufficient"])
        self.assertEqual(result["detected_store_domains"], ["games"])
        self.assertEqual(result["product_direction"], ["tabletop"])
        self.assertEqual(result["personalization"]["product_offering"], "ألعاب لوحية")
        self.assertEqual(result["personalization"]["catalog_scope"], "")
        self.assertEqual(result["confidence_score"], 82)

    def test_cross_field_inconsistency_is_not_rejected(self):
        result = validate_semantic_analysis_payload({
            "description_language": "en",
            "description_sufficient": True,
            "personalization": {"product_offering": "Games"},
            "blocking_missing_information": ["target_audience"],
            "missing_information": ["target_audience"],
        })
        self.assertTrue(result["description_sufficient"])
        self.assertEqual(result["blocking_missing_information"], ["target_audience"])

    def test_top_level_canonical_values_are_projected(self):
        result = validate_semantic_analysis_payload({
            "product_offering": "Handmade jewelry",
            "brand_personality": "Elegant",
        })
        self.assertEqual(result["personalization"]["product_offering"], "Handmade jewelry")
        self.assertEqual(result["personalization"]["brand_personality"], "Elegant")

    def test_input_is_not_mutated_and_output_is_deterministic(self):
        payload = {"personalization": {"target_audience": "Gamers"}, "extra": 1}
        original = deepcopy(payload)
        first = validate_semantic_analysis_payload(payload)
        second = validate_semantic_analysis_payload(payload)
        self.assertEqual(payload, original)
        self.assertEqual(first, second)

    def test_only_non_object_json_is_rejected(self):
        with self.assertRaises(AIUnderstandingValidationError):
            validate_semantic_analysis_payload(["valid", "json", "but", "not", "object"])
