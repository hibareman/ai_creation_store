"""Compatibility tests for the simplified workflow.

The former repair/domain-matching tests were removed because semantic validation
is now owned exclusively by the AI.
"""

from django.test import SimpleTestCase

from .agentic.generation import validate_personalization_constrained_draft


class TechnicalValidationOnlyTests(SimpleTestCase):
    def test_unknown_domain_is_not_rejected(self):
        context = {
            "product_offering": "specialized restoration tools",
            "catalog_scope": "small specialist catalog",
            "target_audience": "professional restorers",
            "target_market": "Morocco",
            "customer_problem": "hard-to-find tools",
            "unique_value_proposition": "clear technical guidance",
            "price_positioning": "professional",
            "brand_personality": "scientific and trustworthy",
            "visual_preferences": "ivory and brown",
            "language_currency": "Arabic and MAD",
        }
        validate_personalization_constrained_draft(
            {"categories": [], "products": []},
            effective_personalization_context=context,
        )
