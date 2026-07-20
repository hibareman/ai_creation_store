"""Phase 6 API Feedback exposure and compatibility tests."""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .agentic.nodes.clarify import clarify_node
from .agentic.nodes.decide import decide_node
from .agentic.nodes.feedback import feedback_node
from .agentic.nodes.human_review import human_review_node
from .agentic.nodes.merge_answers import merge_answers_node
from .agentic.nodes.understand import understand_node
from .agentic.personalization import CORE_PERSONALIZATION_KEYS
from .agentic_production_services import _project_agentic_state_to_public_response
from .constants import (
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .serializers import AIDraftStateResponseSerializer


def _feedback(*, percentage=40, missing=None, sufficient=False, confidence=61):
    return {
        "understood_summary": "We understood: Products or services: Board games.",
        "completion_percentage": percentage,
        "missing_information": list(missing or ["target_audience"]),
        "description_sufficient": sufficient,
        "confidence_score": confidence,
    }


def _question(fact: str) -> dict:
    return {
        "question_id": f"clarification_{fact}_1",
        "question_key": fact,
        "target_fact": fact,
        "question_text": f"Please clarify {fact.replace('_', ' ')}.",
        "reason": "This helps tailor the store.",
        "recommendation": None,
        "answer_type": "single_select",
        "options": ["Option A", "Option B", "Other"],
        "other_option": "Other",
        "allow_custom_answer": True,
        "required": True,
    }


def _draft_payload(questions=None):
    questions = list(questions or [])
    return {
        "store": {},
        "store_settings": {},
        "theme": {},
        "categories": [],
        "products": [],
        "clarification_needed": bool(questions),
        "clarification_questions": questions,
    }


def _terminal_state(*, feedback=None, status=WORKFLOW_STATUS_NEEDS_CLARIFICATION):
    questions = [_question("target_audience")] if status == WORKFLOW_STATUS_NEEDS_CLARIFICATION else []
    state = {
        "store_id": 10,
        "status": status,
        "current_step": "human_review",
        "mode": "clarification" if questions else "draft_ready",
        "clarification_round_count": 0,
        "repair_attempt_count": 0,
        "clarification_questions": questions,
        "draft_payload": _draft_payload(questions),
    }
    if feedback is not None:
        state["feedback"] = deepcopy(feedback)
    return state


class Phase6APIUpdateTests(SimpleTestCase):
    def test_response_includes_latest_feedback_without_recalculation(self):
        expected = _feedback(percentage=37, missing=["custom missing text"], confidence=83)
        result = _project_agentic_state_to_public_response(
            _terminal_state(feedback=expected)
        )
        self.assertEqual(result["feedback"], expected)
        self.assertEqual(result["draft_metadata"]["feedback"], expected)
        self.assertEqual(result["draft_metadata"]["current_step"], "feedback")

    def test_feedback_contract_contains_all_existing_fields(self):
        result = _project_agentic_state_to_public_response(
            _terminal_state(feedback=_feedback())
        )
        self.assertEqual(
            set(result["feedback"]),
            {
                "understood_summary",
                "completion_percentage",
                "missing_information",
                "description_sufficient",
                "confidence_score",
            },
        )

    def test_existing_wrapper_and_payload_types_remain_unchanged(self):
        before = _terminal_state(feedback=_feedback())
        legacy_state = deepcopy(before)
        legacy_state.pop("feedback")
        original_payload = _project_agentic_state_to_public_response(legacy_state)["draft_payload"]
        result = _project_agentic_state_to_public_response(before)
        self.assertEqual(set(result) - {"feedback"}, {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(result["draft_payload"], original_payload)
        self.assertIsInstance(result["store_id"], int)
        self.assertIsInstance(result["draft_payload"], dict)
        self.assertIsInstance(result["draft_metadata"], dict)

    def test_clarification_and_generation_ready_responses_include_feedback(self):
        for status in (WORKFLOW_STATUS_NEEDS_CLARIFICATION, WORKFLOW_STATUS_READY_FOR_REVIEW):
            with self.subTest(status=status):
                result = _project_agentic_state_to_public_response(
                    _terminal_state(feedback=_feedback(), status=status)
                )
                self.assertIn("feedback", result)
                self.assertEqual(result["draft_metadata"]["status"], status)
                expected_mode = "clarification" if status == WORKFLOW_STATUS_NEEDS_CLARIFICATION else "draft_ready"
                self.assertEqual(result["draft_metadata"]["mode"], expected_mode)
                self.assertEqual(result["draft_metadata"]["current_step"], "feedback")

    def test_missing_or_invalid_feedback_is_omitted_without_placeholder(self):
        for value in (None, {}, {"completion_percentage": 10}):
            with self.subTest(value=value):
                state = _terminal_state()
                if value is not None:
                    state["feedback"] = value
                result = _project_agentic_state_to_public_response(state)
                self.assertNotIn("feedback", result)
                self.assertIsNone(result["draft_metadata"]["feedback"])
                self.assertEqual(result["draft_metadata"]["current_step"], "human_review")

    def test_recoverable_failure_remains_valid_and_not_feedback_step(self):
        state = {
            "store_id": 10,
            "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
            "current_step": "recoverable_failure",
            "mode": "failed_recoverable",
            "error_code": "ai_generation_failed",
            "user_message": "Retry later.",
        }
        result = _project_agentic_state_to_public_response(state)
        self.assertNotIn("feedback", result)
        self.assertEqual(result["draft_metadata"]["current_step"], "recoverable_failure")
        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

    def test_serializer_accepts_legacy_and_feedback_responses(self):
        legacy = _project_agentic_state_to_public_response(_terminal_state())
        current = _project_agentic_state_to_public_response(
            _terminal_state(feedback=_feedback())
        )
        for payload in (legacy, current):
            serializer = AIDraftStateResponseSerializer(data=payload)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def test_clarification_questions_are_unchanged_by_feedback_exposure(self):
        state = _terminal_state(feedback=_feedback())
        no_feedback_state = deepcopy(state)
        no_feedback_state.pop("feedback")
        with_feedback = _project_agentic_state_to_public_response(state)
        without_feedback = _project_agentic_state_to_public_response(no_feedback_state)
        self.assertEqual(
            with_feedback["draft_payload"]["clarification_questions"],
            without_feedback["draft_payload"]["clarification_questions"],
        )

    def test_understand_feedback_decide_api_integration(self):
        state = {
            "store_id": 1,
            "tenant_id": 2,
            "user_id": 3,
            "normalized_description": "I want a board-game store.",
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
        }
        provider = Mock()
        provider.analyze_store_description.return_value = _provider_response(
            resolved={"product_offering": "Board games"}, confidence=62
        )
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ):
            state.update(understand_node(state))
        state.update(feedback_node(state))
        generated_feedback = deepcopy(state["feedback"])
        state.update(decide_node(state))
        with patch(
            "AI_Store_Creation_Service.agentic.nodes.clarify.generate_clarification_questions",
            side_effect=lambda **kwargs: [_question(key) for key in kwargs["requested_question_keys"]],
        ):
            state.update(clarify_node(state))
        state.update(human_review_node(state))

        response = _project_agentic_state_to_public_response(state)
        self.assertEqual(response["feedback"], generated_feedback)
        self.assertEqual(response["draft_metadata"]["current_step"], "feedback")
        self.assertEqual(response["draft_metadata"]["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)

    def test_merge_understand_feedback_api_refresh_integration(self):
        answered_question = _question("target_audience")
        state = {
            "workflow_entry": "clarification_resume",
            "store_id": 1,
            "tenant_id": 2,
            "user_id": 3,
            "normalized_description": "I want a board-game store.",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "mode": "clarification",
            "current_step": "human_review",
            "route_decision": "human_review",
            "description_sufficient": False,
            "validation_errors": [],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "clarification_questions": [answered_question],
            "clarification_answers": [{
                "question_key": "target_audience",
                "selected_option": "Other",
                "custom_answer": "Female university students",
            }],
            "effective_personalization_context": {"product_offering": "Board games"},
            "confirmed_personalization_context": {},
            "feedback": _feedback(percentage=10, missing=["stale"], confidence=1),
            "draft_payload": _draft_payload([answered_question]),
            "repair_attempt_count": 0,
        }
        stale_feedback = deepcopy(state["feedback"])
        original_description = state["normalized_description"]
        state.update(merge_answers_node(state))

        provider = Mock()
        provider.analyze_store_description.return_value = _provider_response(
            resolved={
                "product_offering": "Board games",
                "target_audience": "young people",
            },
            confidence=75,
        )
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ):
            state.update(understand_node(state))
        self.assertEqual(state["normalized_description"], original_description)
        self.assertEqual(
            provider.analyze_store_description.call_args.kwargs["clarification_context"]["clarification_facts"]["target_audience"],
            "Female university students",
        )
        state.update(feedback_node(state))
        refreshed_feedback = deepcopy(state["feedback"])
        self.assertNotEqual(refreshed_feedback, stale_feedback)
        self.assertEqual(refreshed_feedback["completion_percentage"], 20)
        self.assertNotIn("target_audience", " ".join(refreshed_feedback["missing_information"]))

        state.update(decide_node(state))
        with patch(
            "AI_Store_Creation_Service.agentic.nodes.clarify.generate_clarification_questions",
            side_effect=lambda **kwargs: [_question(key) for key in kwargs["requested_question_keys"]],
        ):
            state.update(clarify_node(state))
        state.update(human_review_node(state))
        response = _project_agentic_state_to_public_response(state)

        self.assertEqual(response["feedback"], refreshed_feedback)
        self.assertNotEqual(response["feedback"], stale_feedback)
        self.assertNotIn(
            "target_audience",
            [q["question_key"] for q in response["draft_payload"]["clarification_questions"]],
        )
        self.assertEqual(set(response) - {"feedback"}, {"store_id", "draft_payload", "draft_metadata"})


def _provider_response(*, resolved: dict[str, str], confidence: int):
    personalization = {key: "" for key in CORE_PERSONALIZATION_KEYS}
    personalization.update(resolved)
    unresolved = [key for key in CORE_PERSONALIZATION_KEYS if not personalization[key]]
    payload = {
        "description_language": "en",
        "description_sufficient": not unresolved,
        "detected_store_domains": ["board games"],
        "target_audience": resolved.get("target_audience", ""),
        "product_direction": [resolved.get("product_offering", "Board games")],
        "personalization": personalization,
        "blocking_missing_information": unresolved,
        "missing_information": [f"Please clarify {key}." for key in unresolved],
        "confidence_score": confidence,
        "ambiguities": [],
    }
    return {"choices": [{"message": {"content": payload}}]}
