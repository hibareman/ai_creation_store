from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from .agentic.nodes.human_review import human_review_node
from .agentic.nodes.repair import repair_node
from .agentic.nodes.validate import validate_node


VALID_DRAFT = {
    "store": {"name": "Coffee Home", "description": "Specialty coffee."},
    "store_settings": {"currency": "SAR", "language": "ar", "timezone": "UTC"},
    "theme": {
        "theme_template": "Minimal", "primary_color": "#112233",
        "secondary_color": "#445566", "font_family": "Cairo",
        "logo_url": "", "banner_url": "",
    },
    "categories": [{"name": "Coffee"}, {"name": "Tools"}],
    "products": [
        {"name": "Beans", "description": "Fresh beans", "price": 30,
         "sku": "B-1", "category_name": "Coffee", "stock_quantity": 5,
         "image_url": ""},
        {"name": "Dripper", "description": "Coffee dripper", "price": 50,
         "sku": "D-1", "category_name": "Tools", "stock_quantity": 3,
         "image_url": ""},
    ],
    "clarification_needed": False,
    "clarification_questions": [],
}

BASE_STATE = {
    "store_id": 1, "tenant_id": 1, "user_id": 1,
    "normalized_description": "Specialty coffee store",
    "available_theme_templates": ["Minimal"],
    "mode": "draft_ready", "repair_attempt_count": 0,
    "clarification_facts": {},
}


class DraftValidationRepairTests(TestCase):
    def test_valid_draft_routes_to_review_and_sets_ready_step(self):
        state = {**BASE_STATE, "draft_payload": deepcopy(VALID_DRAFT)}
        result = validate_node(state)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["validation_errors"], [])
        review = human_review_node({**state, **result})
        self.assertEqual(review["current_step"], "ready_for_review")

    def test_invalid_theme_routes_to_partial_repair_then_revalidation(self):
        invalid = deepcopy(VALID_DRAFT)
        invalid["theme"]["primary_color"] = "not-a-color"
        state = {**BASE_STATE, "draft_payload": invalid}
        validation = validate_node(state)
        self.assertEqual(validation["route_decision"], "repair")
        self.assertTrue(validation["validation_errors"])
        self.assertTrue(validation["validation_errors"][0]["path"].startswith("theme"))

        repaired = deepcopy(VALID_DRAFT)
        with patch(
            "AI_Store_Creation_Service.agentic.nodes.repair.repair_draft_payload",
            return_value=repaired,
        ):
            repair = repair_node({**state, **validation})
        self.assertEqual(repair["route_decision"], "validate")
        self.assertEqual(repair["repair_attempt_count"], 1)

        final_validation = validate_node({**state, **validation, **repair})
        self.assertEqual(final_validation["route_decision"], "human_review")
        self.assertEqual(final_validation["validation_errors"], [])

    def test_invalid_draft_fails_recoverably_after_max_attempts(self):
        invalid = deepcopy(VALID_DRAFT)
        invalid["store"]["name"] = ""
        state = {
            **BASE_STATE, "draft_payload": invalid,
            "repair_attempt_count": 3,
        }
        result = validate_node(state)
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["repair_attempt_count"], 3)
        self.assertTrue(result["validation_errors"])
        self.assertTrue(result["validation_errors"][0]["path"].startswith("store"))
