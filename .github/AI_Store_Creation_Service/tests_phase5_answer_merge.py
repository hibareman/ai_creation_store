"""Phase 5 deterministic Answer Merge tests."""

import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from .agentic.feedback import build_feedback
from .agentic.merging import AIMergeValidationError, merge_clarification_answers
from .agentic.nodes.feedback import feedback_node
from .agentic.nodes.merge_answers import merge_answers_node
from .agentic.nodes.understand import understand_node
from .agentic.personalization import CORE_PERSONALIZATION_KEYS
from .agentic.routing import route_after_merge


def question(fact="target_audience", answer_type="single_select"):
    selectable = answer_type == "single_select"
    return {
        "question_id": f"clarification_{fact}_1",
        "question_key": fact,
        "target_fact": fact,
        "question_text": "Who are your primary customers?",
        "reason": "This helps tailor the store.",
        "recommendation": None,
        "answer_type": answer_type,
        "options": ["Students", "Families", "Other"] if selectable else [],
        "other_option": "Other" if selectable else None,
        "allow_custom_answer": True,
        "required": True,
    }


def merge(
    *,
    questions=None,
    answers=None,
    history=None,
    facts=None,
    round_count=0,
    ai_context=None,
    confirmed=None,
):
    return merge_clarification_answers(
        clarification_questions=questions or [question()],
        clarification_answers=answers or [{"question_key": "target_audience", "selected_option": "Students"}],
        clarification_history=history or [],
        clarification_facts=facts or {},
        clarification_round_count=round_count,
        previous_confirmed_context=confirmed or {},
        latest_ai_context=ai_context or {},
    )


class Phase5AnswerMergeTests(unittest.TestCase):
    def test_merchant_answer_overrides_previous_ai_inference(self):
        result = merge(ai_context={"target_audience": "young people"}, answers=[
            {"question_key": "target_audience", "selected_option": "Other", "custom_answer": "Female university students"}
        ])
        self.assertEqual(result["merged_personalization_context"]["target_audience"], "Female university students")

    def test_original_description_remains_unchanged(self):
        state = self._resume_state()
        original = state["normalized_description"]
        update = merge_answers_node(state)
        self.assertTrue(update["merge_valid"])
        self.assertNotIn("normalized_description", update)
        self.assertEqual(state["normalized_description"], original)

    def test_answers_merge_and_unrelated_facts_remain(self):
        ai_context = {"product_offering": "Handmade mugs", "target_audience": "Adults"}
        result = merge(ai_context=ai_context)
        self.assertEqual(result["merged_personalization_context"]["product_offering"], "Handmade mugs")
        self.assertEqual(result["merged_personalization_context"]["target_audience"], "Students")

    def test_multiple_rounds_merge(self):
        first = merge()
        second_q = question("target_market")
        second_q["question_id"] = "clarification_target_market_1"
        second_q["question_text"] = "Where will you sell?"
        second = merge(
            questions=[second_q],
            answers=[{"question_key": "target_market", "selected_option": "Other", "custom_answer": "Warsaw and Kraków"}],
            history=first["clarification_history"], facts=first["clarification_facts"], round_count=1,
        )
        self.assertEqual(second["clarification_facts"]["target_audience"], "Students")
        self.assertEqual(second["clarification_facts"]["target_market"], "Warsaw and Kraków")

    def test_other_and_free_text_preserved_exactly(self):
        custom = "  Gamers, collectors — كبار السن  "
        result = merge(answers=[{"question_key": "target_audience", "selected_option": "Other", "custom_answer": custom}])
        self.assertEqual(result["clarification_facts"]["target_audience"], custom)
        free_q = question("customer_problem", "free_text")
        free = "  Hard-to-find replacement parts\nfor old consoles  "
        result2 = merge(questions=[free_q], answers=[{"question_key": "customer_problem", "selected_option": free}])
        self.assertEqual(result2["clarification_facts"]["customer_problem"], free)

    def test_answer_order_does_not_affect_merged_context(self):
        q1 = question("target_audience")
        q2 = question("target_market"); q2["question_id"] = "clarification_target_market_1"
        q2["question_text"] = "Where will you sell?"
        a1 = {"question_key": "target_audience", "selected_option": "Students"}
        a2 = {"question_key": "target_market", "selected_option": "Other", "custom_answer": "Poland"}
        one = merge(questions=[q1, q2], answers=[a1, a2])
        two = merge(questions=[q1, q2], answers=[a2, a1])
        self.assertEqual(one["merged_personalization_context"], two["merged_personalization_context"])

    def test_duplicate_merge_is_deterministic(self):
        kwargs = dict(ai_context={"product_offering": "Books"})
        self.assertEqual(merge(**deepcopy(kwargs)), merge(**deepcopy(kwargs)))

    def test_unknown_target_fact_rejected(self):
        q = question("unknown_fact")
        with self.assertRaises(AIMergeValidationError):
            merge(questions=[q], answers=[{"question_key": "unknown_fact", "selected_option": "Students"}])

    def test_invalid_answer_type_rejected(self):
        with self.assertRaises(AIMergeValidationError):
            merge(answers=[{"question_key": "target_audience", "selected_option": "Not an option"}])

    def test_answered_target_facts_are_canonical_and_persistent(self):
        result = merge()
        self.assertEqual(result["answered_target_facts"], ["target_audience"])
        self.assertTrue(set(result["answered_target_facts"]).issubset(CORE_PERSONALIZATION_KEYS))

    def test_merge_node_prepares_next_understand_with_full_context(self):
        state = self._resume_state()
        state["effective_personalization_context"] = {
            "product_offering": "Board games",
            "target_audience": "AI guess",
        }
        update = merge_answers_node(state)
        self.assertEqual(update["clarification_facts"]["target_audience"], "Students")
        self.assertEqual(update["merged_personalization_context"]["product_offering"], "Board games")
        self.assertEqual(
            update["confirmed_personalization_context"],
            {"target_audience": "Students"},
        )
        self.assertNotIn("normalized_description", update)
        self.assertEqual(update["current_step"], "merge_answers")

    def test_ai_inferred_values_are_not_marked_confirmed(self):
        result = merge(
            ai_context={
                "product_offering": "Board games",
                "target_audience": "young people",
            },
            answers=[{
                "question_key": "target_audience",
                "selected_option": "Other",
                "custom_answer": "Female university students",
            }],
        )
        self.assertEqual(
            result["merged_personalization_context"],
            {
                "product_offering": "Board games",
                "target_audience": "Female university students",
            },
        )
        self.assertEqual(
            result["confirmed_personalization_context"],
            {"target_audience": "Female university students"},
        )
        self.assertEqual(result["answered_target_facts"], ["target_audience"])

    def test_previous_confirmed_answers_survive_later_rounds(self):
        first = merge(answers=[{
            "question_key": "target_audience",
            "selected_option": "Other",
            "custom_answer": "Female university students",
        }])
        second_q = question("brand_personality", "free_text")
        second_q["question_text"] = "How should the brand feel?"
        second = merge(
            questions=[second_q],
            answers=[{
                "question_key": "brand_personality",
                "selected_option": "Friendly and modern",
            }],
            history=first["clarification_history"],
            facts=first["clarification_facts"],
            round_count=1,
            ai_context={"product_offering": "Board games"},
            confirmed=first["confirmed_personalization_context"],
        )
        self.assertEqual(
            second["confirmed_personalization_context"],
            {
                "target_audience": "Female university students",
                "brand_personality": "Friendly and modern",
            },
        )
        self.assertEqual(
            second["merged_personalization_context"]["product_offering"],
            "Board games",
        )

    def test_latest_answer_overrides_previous_merchant_confirmation(self):
        result = merge(
            ai_context={"target_audience": "young people"},
            confirmed={"target_audience": "Students"},
            answers=[{
                "question_key": "target_audience",
                "selected_option": "Other",
                "custom_answer": "Professional esports players",
            }],
        )
        self.assertEqual(
            result["confirmed_personalization_context"]["target_audience"],
            "Professional esports players",
        )
        self.assertEqual(
            result["merged_personalization_context"]["target_audience"],
            "Professional esports players",
        )

    def test_input_values_are_not_mutated(self):
        questions = [question()]
        answers = [{"question_key": "target_audience", "selected_option": "Students"}]
        ai_context = {"product_offering": "Board games"}
        confirmed = {"target_market": "Poland"}
        inputs = deepcopy((questions, answers, ai_context, confirmed))
        merge(questions=questions, answers=answers, ai_context=ai_context, confirmed=confirmed)
        self.assertEqual((questions, answers, ai_context, confirmed), inputs)

    def test_real_merge_understand_feedback_node_chain(self):
        state = self._resume_state()
        state["effective_personalization_context"] = {
            "product_offering": "Board games",
            "target_audience": "young people",
        }
        state["confirmed_personalization_context"] = {}
        state["feedback"] = {
            "understood_summary": "STALE",
            "completion_percentage": 10,
            "missing_information": ["stale"],
            "description_sufficient": False,
            "confidence_score": 1,
        }
        state["clarification_answers"] = [{
            "question_key": "target_audience",
            "selected_option": "Other",
            "custom_answer": "Female university students",
        }]
        original_description = state["normalized_description"]

        merge_update = merge_answers_node(state)
        self.assertTrue(merge_update["merge_valid"])
        self.assertEqual(route_after_merge({**state, **merge_update}), "understand")
        self.assertEqual(state["normalized_description"], original_description)
        self.assertEqual(
            merge_update["confirmed_personalization_context"],
            {"target_audience": "Female university students"},
        )
        self.assertEqual(
            merge_update["merged_personalization_context"],
            {
                "product_offering": "Board games",
                "target_audience": "Female university students",
            },
        )

        merged_state = {**state, **merge_update}
        provider = Mock()
        provider.analyze_store_description.return_value = _provider_response_after_merge()
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ):
            understand_update = understand_node(merged_state)

        self.assertTrue(understand_update["understanding_valid"])
        call = provider.analyze_store_description.call_args.kwargs
        self.assertEqual(call["normalized_description"], original_description)
        self.assertEqual(
            call["clarification_context"]["clarification_facts"]["target_audience"],
            "Female university students",
        )
        self.assertEqual(
            understand_update["effective_personalization_context"]["target_audience"],
            "Female university students",
        )
        self.assertNotIn(
            "target_audience", understand_update["missing_core_personalization_keys"]
        )
        self.assertIn(
            "brand_personality", understand_update["missing_core_personalization_keys"]
        )

        latest_state = {**merged_state, **understand_update}
        feedback_update = feedback_node(latest_state)
        refreshed = feedback_update["feedback"]
        self.assertNotEqual(refreshed, state["feedback"])
        self.assertEqual(refreshed["completion_percentage"], 20)
        self.assertEqual(refreshed["confidence_score"], 70)
        self.assertNotEqual(refreshed["missing_information"], ["stale"])
        self.assertNotIn("target audience", " ".join(refreshed["missing_information"]).lower())

    def test_feedback_recomputed_from_latest_understand_output(self):
        before = {"understanding_valid": True, "description_language": "en", "effective_personalization_context": {}, "missing_information": list(CORE_PERSONALIZATION_KEYS), "description_sufficient": False, "confidence_score": 20}
        after = deepcopy(before)
        after["effective_personalization_context"] = {k: "v" for k in CORE_PERSONALIZATION_KEYS}
        after["missing_information"] = []
        after["description_sufficient"] = True
        after["confidence_score"] = 95
        self.assertEqual(build_feedback(before)["completion_percentage"], 0)
        refreshed = build_feedback(after)
        self.assertEqual(refreshed["completion_percentage"], 100)
        self.assertEqual(refreshed["missing_information"], [])
        self.assertEqual(refreshed["confidence_score"], 95)

    def test_json_serialization(self):
        json.dumps(merge(), ensure_ascii=False, allow_nan=False)

    def test_recoverable_failure_unchanged(self):
        update = merge_answers_node({"workflow_entry": "clarification_resume"})
        self.assertFalse(update["merge_valid"])
        self.assertEqual(update["status"], "failed_recoverable")

    @staticmethod
    def _resume_state():
        q = question()
        return {
            "workflow_entry": "clarification_resume", "status": "needs_clarification",
            "mode": "clarification", "current_step": "human_review",
            "route_decision": "human_review", "description_sufficient": False,
            "validation_errors": [], "store_id": 1, "tenant_id": 2, "user_id": 3,
            "normalized_description": "I want a board-game store.",
            "clarification_round_count": 0, "clarification_history": [],
            "clarification_facts": {}, "clarification_questions": [q],
            "clarification_answers": [{"question_key": "target_audience", "selected_option": "Students"}],
            "draft_payload": {"clarification_needed": True, "clarification_questions": [q]},
        }


def _provider_response_after_merge():
    personalization = {key: "" for key in CORE_PERSONALIZATION_KEYS}
    personalization["product_offering"] = "Board games"
    personalization["target_audience"] = "young people"
    unresolved = [
        key for key in CORE_PERSONALIZATION_KEYS
        if key not in {"product_offering", "target_audience"}
    ]
    payload = {
        "description_language": "en",
        "description_sufficient": False,
        "detected_store_domains": ["board games"],
        "target_audience": "Female university students",
        "product_direction": ["Board games"],
        "personalization": personalization,
        "blocking_missing_information": unresolved,
        "missing_information": [f"Please clarify {key.replace('_', ' ')}." for key in unresolved],
        "confidence_score": 70,
        "ambiguities": [],
    }
    return {"choices": [{"message": {"content": payload}}]}


if __name__ == "__main__":
    unittest.main()
