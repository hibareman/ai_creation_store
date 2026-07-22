"""Focused Phase 7 public API contract and OpenAPI tests."""

import json

from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator

from .agentic.personalization import CORE_PERSONALIZATION_KEYS
from .agentic.merging import (
    AIMergeValidationError,
    validate_clarification_answer_submission,
)
from .agentic_production_services import _project_agentic_state_to_public_response
from .constants import WORKFLOW_STATUS_NEEDS_CLARIFICATION
from .serializers import (
    AIAgenticClarificationRequestSerializer,
    AIClarificationRequestSerializer,
    AIDraftStateResponseSerializer,
)


class Phase7APIContractTests(SimpleTestCase):
    def _state(self):
        return {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "current_step": "clarify",
            "mode": "clarification",
            "clarification_round_count": 1,
            "repair_attempt_count": 0,
            "personalization_progress": {
                "resolved_core_count": 6,
                "total_core_count": 10,
                "core_complete": False,
                "missing_core_keys": list(CORE_PERSONALIZATION_KEYS[6:]),
            },
            "draft_payload": {
                "clarification_needed": True,
                "clarification_questions": [
                    {
                        "question_key": "price_positioning",
                        "question_text": "How should prices be positioned?",
                        "options": ["Affordable", "Premium", "Other"],
                        "other_option": "Other",
                    }
                ],
            },
            "clarification_questions": [
                {
                    "question_key": "price_positioning",
                    "question_text": "How should prices be positioned?",
                    "options": ["Affordable", "Premium", "Other"],
                    "other_option": "Other",
                }
            ],
            "route_decision": "clarify",
            "prompt": "secret prompt",
            "provider_response": {"raw": "secret"},
        }

    def test_public_response_contract_contains_only_safe_progress_metadata(self):
        result = _project_agentic_state_to_public_response(self._state())
        self.assertEqual(set(result), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(
            result["draft_metadata"]["personalization_progress"],
            self._state()["personalization_progress"],
        )
        serialized = json.dumps(result)
        for hidden in (
            "tenant_id", "user_id", "prompt", "provider_response",
            "route_decision", "cache_key", "traceback",
        ):
            self.assertNotIn(hidden, serialized)
        serializer = AIDraftStateResponseSerializer(data=result)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_normal_and_other_agentic_answers_are_strict(self):
        normal = {"clarification_answers": [{
            "question_key": "price_positioning", "selected_option": "Premium",
        }]}
        other = {"clarification_answers": [{
            "question_key": "product_offering", "selected_option": "Other",
            "custom_answer": "Handmade natural soaps",
        }]}
        for payload in (normal, other):
            serializer = AIAgenticClarificationRequestSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), serializer.errors)
        invalid = AIAgenticClarificationRequestSerializer(data={
            **normal, "tenant_id": 101,
        })
        self.assertFalse(invalid.is_valid())
        one_character = AIAgenticClarificationRequestSerializer(data={
            "clarification_answers": [{
                "question_key": "product_offering",
                "selected_option": "Other",
                "custom_answer": "x",
            }]
        })
        self.assertFalse(one_character.is_valid())

        question = [{
            "question_key": "product_offering",
            "question_text": "What will the store sell?",
            "options": ["Coffee", "Fashion", "Other"],
            "other_option": "Other",
        }]
        self.assertEqual(
            validate_clarification_answer_submission(
                clarification_questions=question,
                clarification_answers=other["clarification_answers"],
            )[0]["custom_answer"],
            "Handmade natural soaps",
        )
        with self.assertRaises(AIMergeValidationError):
            validate_clarification_answer_submission(
                clarification_questions=question,
                clarification_answers=[{
                    "question_key": "product_offering",
                    "selected_option": "Coffee",
                    "custom_answer": "Not allowed",
                }],
            )

    def test_malformed_progress_uses_canonical_safe_fallback(self):
        fallback = {
            "resolved_core_count": 0,
            "total_core_count": 10,
            "core_complete": False,
            "missing_core_keys": list(CORE_PERSONALIZATION_KEYS),
        }
        malformed_values = (
            None,
            {
                "resolved_core_count": 6, "total_core_count": 9,
                "core_complete": False,
                "missing_core_keys": list(CORE_PERSONALIZATION_KEYS[6:]),
            },
            {
                "resolved_core_count": 6, "total_core_count": 10,
                "core_complete": False,
                "missing_core_keys": list(reversed(CORE_PERSONALIZATION_KEYS[6:])),
            },
            {
                "resolved_core_count": 8, "total_core_count": 10,
                "core_complete": False,
                "missing_core_keys": ["visual_preferences", "visual_preferences"],
            },
            {
                "resolved_core_count": 7, "total_core_count": 10,
                "core_complete": True,
                "missing_core_keys": list(CORE_PERSONALIZATION_KEYS[6:]),
            },
        )
        for progress in malformed_values:
            with self.subTest(progress=progress):
                state = self._state()
                state["personalization_progress"] = progress
                result = _project_agentic_state_to_public_response(state)
                self.assertEqual(
                    result["draft_metadata"]["personalization_progress"], fallback
                )

    def test_nested_internal_fields_are_removed_from_public_draft(self):
        state = self._state()
        internal = {
            "tenant_id": 101,
            "user_id": 7,
            "prompt": "secret",
            "provider_response": "secret",
            "choices": [],
            "route_decision": "repair",
            "cache_key": "secret",
            "traceback": "secret",
            "blueprint": {"locked_constraints": {}},
            "effective_personalization_context": {"target_market": "secret"},
        }
        state["draft_payload"].update(internal)
        state["draft_payload"]["store"] = {"name": "Safe", **internal}
        state["clarification_questions"][0].update(internal)
        result = _project_agentic_state_to_public_response(state)
        serialized = json.dumps(result)
        for key in internal:
            self.assertNotIn(f'"{key}"', serialized)
        self.assertEqual(result["draft_payload"]["store"], {"name": "Safe"})

    def test_legacy_clarification_inputs_remain_compatible(self):
        for value in ("More details", {"store_type": "Fashion"}, ["Fashion"]):
            serializer = AIClarificationRequestSerializer(
                data={"clarification_answers": value}
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_openapi_preserves_urls_and_documents_phase7_fields(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = schema["paths"]
        self.assertIn("/api/ai/stores/draft/start/", paths)
        self.assertIn("/api/ai/stores/{store_id}/draft/", paths)
        self.assertIn("/api/ai/stores/{store_id}/draft/clarify/", paths)
        self.assertFalse(any("agentic" in path.casefold() for path in paths))
        serialized = json.dumps(schema)
        self.assertIn("personalization_progress", serialized)
        self.assertIn("custom_answer", serialized)
        self.assertIn("Handmade natural soaps", serialized)
        self.assertIn('"minLength": 2', serialized)
        self.assertIn('"ai_analysis"', serialized)
        self.assertIn('"ai_changes"', serialized)
        self.assertIn('"analysis_updated"', serialized)
        self.assertIn('"target_section"', serialized)
        self.assertIn('"user_instruction"', serialized)

        agentic_paths = {
            path: operations
            for path, operations in paths.items()
            if path.startswith("/api/ai/stores/")
        }
        self.assertTrue(agentic_paths)
        for path, operations in agentic_paths.items():
            for method, operation in operations.items():
                if method.casefold() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                self.assertEqual(
                    operation.get("tags"),
                    ["Agentic Updates"],
                    msg=f"Unexpected Swagger tag for {method.upper()} {path}",
                )

        self.assertIn("Regenerate Theme", serialized)
        self.assertIn("Regenerate Products", serialized)
        self.assertIn("Regenerate Categories", serialized)
        self.assertIn("display-only", serialized)
