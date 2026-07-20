"""Focused tests for the simplified AI-owned semantic workflow."""

from django.test import SimpleTestCase

from .agentic.graph import build_agentic_graph
from .agentic.generation import validate_personalization_constrained_draft
from .agentic.routing import route_after_decide, route_after_validate


class SimplifiedWorkflowTests(SimpleTestCase):
    def test_graph_excludes_blueprint_and_repair_nodes(self):
        graph = build_agentic_graph()
        self.assertNotIn("blueprint", graph.nodes)
        self.assertNotIn("repair", graph.nodes)

    def test_complete_understanding_routes_directly_to_generate(self):
        self.assertEqual(route_after_decide({"route_decision": "generate"}), "generate")

    def test_structurally_valid_result_routes_to_review(self):
        self.assertEqual(
            route_after_validate({"route_decision": "human_review"}),
            "human_review",
        )

    def test_backend_does_not_reject_unknown_product_domain(self):
        payload = {
            "store": {}, "store_settings": {}, "theme": {},
            "categories": [], "products": [],
            "clarification_needed": False, "clarification_questions": [],
        }
        context = {
            "product_offering": "أدوات ترميم المخطوطات",
            "catalog_scope": "كتالوج متخصص",
            "target_audience": "المرممون",
            "target_market": "المغرب",
            "customer_problem": "صعوبة إيجاد الأدوات",
            "unique_value_proposition": "شرح تقني واضح",
            "price_positioning": "احترافي",
            "brand_personality": "علمية",
            "visual_preferences": "عاجي وبني",
            "language_currency": "العربية وMAD",
        }
        validate_personalization_constrained_draft(
            payload,
            effective_personalization_context=context,
        )
