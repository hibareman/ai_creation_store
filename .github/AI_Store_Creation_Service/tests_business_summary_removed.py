from django.test import SimpleTestCase

from AI_Store_Creation_Service.agentic.understanding import (
    validate_semantic_analysis_payload,
)


class BusinessSummaryRemovedTests(SimpleTestCase):
    def _payload(self):
        keys = (
            "product_offering", "catalog_scope", "target_audience",
            "target_market", "customer_problem",
            "unique_value_proposition", "price_positioning",
            "brand_personality", "visual_preferences",
            "language_currency",
        )
        return {
            "description_language": "ar",
            "description_sufficient": False,
            "detected_store_domains": ["coffee"],
            "target_audience": "",
            "product_direction": ["قهوة"],
            "personalization": {key: ("قهوة" if key == "product_offering" else "") for key in keys},
            "blocking_missing_information": [key for key in keys if key != "product_offering"],
            "ambiguities": [],
        }

    def test_business_summary_is_not_required(self):
        result = validate_semantic_analysis_payload(self._payload())
        self.assertNotIn("business_summary", result)

    def test_legacy_business_summary_is_ignored(self):
        payload = self._payload()
        payload["business_summary"] = ""
        result = validate_semantic_analysis_payload(payload)
        self.assertNotIn("business_summary", result)
