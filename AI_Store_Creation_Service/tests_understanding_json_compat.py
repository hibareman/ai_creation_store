import json
from copy import deepcopy
from unittest import TestCase

from AI_Store_Creation_Service.agentic.personalization import CORE_PERSONALIZATION_KEYS
from AI_Store_Creation_Service.agentic.understanding import (
    AIUnderstandingValidationError,
    validate_semantic_analysis_payload,
)
from AI_Store_Creation_Service.parsers import parse_provider_raw_response_to_dict


def base_payload():
    return {
        "description_language": "en",
        "description_sufficient": False,
        "detected_store_domains": ["board games"],
        "target_audience": "young people",
        "product_direction": ["strategy games"],
        "personalization": {
            "product_offering": "Board games",
            "target_audience": "young people",
        },
        "blocking_missing_information": [
            key for key in CORE_PERSONALIZATION_KEYS
            if key not in {"product_offering", "target_audience"}
        ],
        "missing_information": ["More store details are needed"],
        "confidence_score": 0.82,
        "ambiguities": [],
    }


class UnderstandingJsonCompatibilityTests(TestCase):
    def test_accepts_probability_confidence_and_converts_to_percentage(self):
        result = validate_semantic_analysis_payload(base_payload())
        self.assertEqual(result["confidence_score"], 82)

    def test_accepts_percentage_float_confidence(self):
        payload = base_payload()
        payload["confidence_score"] = 61.5
        result = validate_semantic_analysis_payload(payload)
        self.assertEqual(result["confidence_score"], 62)

    def test_accepts_single_common_wrapper(self):
        result = validate_semantic_analysis_payload({"analysis": base_payload()})
        self.assertEqual(result["personalization"]["product_offering"], "Board games")

    def test_fills_missing_canonical_personalization_keys_with_empty_strings(self):
        result = validate_semantic_analysis_payload(base_payload())
        self.assertEqual(set(result["personalization"]), set(CORE_PERSONALIZATION_KEYS))
        self.assertEqual(result["personalization"]["catalog_scope"], "")

    def test_ignores_known_presentation_only_fields(self):
        payload = base_payload()
        payload["completion_percentage"] = 20
        payload["understood_summary"] = {"product_offering": "Board games"}
        result = validate_semantic_analysis_payload(payload)
        self.assertNotIn("completion_percentage", result)
        self.assertNotIn("understood_summary", result)

    def test_unknown_business_field_is_ignored(self):
        payload = base_payload()
        payload["invented_business_field"] = "x"
        result = validate_semantic_analysis_payload(payload)
        self.assertNotIn("invented_business_field", result)

    def test_unknown_personalization_key_is_ignored(self):
        payload = base_payload()
        payload["personalization"]["non_canonical"] = "x"
        result = validate_semantic_analysis_payload(payload)
        self.assertNotIn("non_canonical", result["personalization"])

    def test_input_is_not_mutated(self):
        payload = base_payload()
        original = deepcopy(payload)
        validate_semantic_analysis_payload(payload)
        self.assertEqual(payload, original)

    def test_result_is_json_serializable(self):
        json.dumps(validate_semantic_analysis_payload(base_payload()))

    def test_parser_accepts_fenced_json(self):
        raw = {"choices": [{"message": {"content": "```json\n" + json.dumps(base_payload()) + "\n```"}}]}
        parsed = parse_provider_raw_response_to_dict(raw)
        self.assertEqual(parsed["confidence_score"], 0.82)

    def test_parser_accepts_double_encoded_json_string(self):
        content = json.dumps(json.dumps(base_payload()))
        raw = {"choices": [{"message": {"content": content}}]}
        parsed = parse_provider_raw_response_to_dict(raw)
        self.assertEqual(parsed["personalization"]["product_offering"], "Board games")
