"""Phase 3 Feedback Layer tests."""

import json

from unittest.mock import patch

from django.test import SimpleTestCase

from .agentic.feedback import build_feedback, validate_feedback_contract
from .agentic.graph import build_agentic_graph
from .agentic.nodes.feedback import feedback_node
from .agentic.personalization import CORE_PERSONALIZATION_KEYS


def state_for(*, language="en", resolved=10, missing=None, sufficient=None, confidence=90):
    context = {
        key: f"value {index + 1}" for index, key in enumerate(CORE_PERSONALIZATION_KEYS[:resolved])
    }
    return {
        "understanding_valid": True,
        "description_language": language,
        "effective_personalization_context": context,
        "missing_information": list(missing or []),
        "description_sufficient": resolved == 10 if sufficient is None else sufficient,
        "confidence_score": confidence,
    }


class FeedbackLayerTests(SimpleTestCase):
    def test_graph_places_feedback_between_understand_and_decide(self):
        graph = build_agentic_graph()
        self.assertIn("feedback", graph.nodes)

    def test_complete_description(self):
        feedback = build_feedback(state_for(resolved=10, missing=[]))
        self.assertEqual(feedback["completion_percentage"], 100)
        self.assertTrue(feedback["description_sufficient"])
        self.assertEqual(feedback["missing_information"], [])

    def test_incomplete_description(self):
        missing = ["Please specify the target market."]
        feedback = build_feedback(state_for(resolved=6, missing=missing, sufficient=False))
        self.assertEqual(feedback["completion_percentage"], 60)
        self.assertFalse(feedback["description_sufficient"])
        self.assertEqual(feedback["missing_information"], missing)

    def test_arabic_summary_preserves_language(self):
        feedback = build_feedback(state_for(language="ar", resolved=2))
        self.assertTrue(feedback["understood_summary"].startswith("فهمنا أن"))

    def test_english_summary_preserves_language(self):
        feedback = build_feedback(state_for(language="en", resolved=2))
        self.assertTrue(feedback["understood_summary"].startswith("We understood:"))

    def test_all_ten_facts_complete(self):
        self.assertEqual(build_feedback(state_for(resolved=10))["completion_percentage"], 100)

    def test_all_ten_facts_missing(self):
        feedback = build_feedback(state_for(resolved=0, sufficient=False, confidence=10))
        self.assertEqual(feedback["completion_percentage"], 0)
        self.assertFalse(feedback["description_sufficient"])

    def test_missing_information_is_not_rewritten(self):
        missing = ["السوق المستهدف غير محدد", "حدد الفئة السعرية"]
        feedback = build_feedback(state_for(language="ar", resolved=8, missing=missing))
        self.assertEqual(feedback["missing_information"], missing)

    def test_confidence_score_is_copied_not_used_for_completion(self):
        low = build_feedback(state_for(resolved=7, confidence=1))
        high = build_feedback(state_for(resolved=7, confidence=100))
        self.assertEqual(low["completion_percentage"], high["completion_percentage"])
        self.assertEqual(low["confidence_score"], 1)
        self.assertEqual(high["confidence_score"], 100)


    def test_completion_percentage_ignores_word_count(self):
        short = state_for(resolved=5)
        long = state_for(resolved=5)
        long["effective_personalization_context"] = {
            key: ("many words " * 100).strip()
            for key in CORE_PERSONALIZATION_KEYS[:5]
        }
        self.assertEqual(build_feedback(short)["completion_percentage"], 50)
        self.assertEqual(build_feedback(long)["completion_percentage"], 50)

    def test_completion_percentage_ignores_clarification_question_count(self):
        base = state_for(resolved=3)
        with_no_questions = dict(base, clarification_questions=[])
        with_many_questions = dict(
            base,
            clarification_questions=[{"question": str(index)} for index in range(25)],
        )
        self.assertEqual(build_feedback(with_no_questions)["completion_percentage"], 30)
        self.assertEqual(build_feedback(with_many_questions)["completion_percentage"], 30)

    def test_completion_percentage_uses_only_canonical_facts(self):
        state = state_for(resolved=0, sufficient=False)
        state["effective_personalization_context"] = {
            "store_name": "Complete Store",
            "non_canonical_fact": "value",
        }
        self.assertEqual(build_feedback(state)["completion_percentage"], 0)

    def test_understood_summary_preserves_confirmed_value_without_rewriting(self):
        state = state_for(resolved=0, language="en", sufficient=False)
        confirmed_value = "Premium   handmade mugs"
        state["effective_personalization_context"] = {
            "product_offering": confirmed_value,
        }
        feedback = build_feedback(state)
        self.assertIn(confirmed_value, feedback["understood_summary"])

    def test_understood_summary_does_not_include_missing_or_noncanonical_data(self):
        state = state_for(resolved=1, missing=["Target market: Poland"])
        state["effective_personalization_context"]["store_name"] = "Invented Store"
        summary = build_feedback(state)["understood_summary"]
        self.assertNotIn("Poland", summary)
        self.assertNotIn("Invented Store", summary)

    def test_feedback_json_serialization_round_trip(self):
        feedback = build_feedback(state_for(language="ar", resolved=10))
        serialized = json.dumps(feedback, ensure_ascii=False, allow_nan=False)
        self.assertEqual(json.loads(serialized), feedback)

    def test_feedback_builder_is_deterministic(self):
        state = state_for(
            language="ar",
            resolved=7,
            missing=["حدد السوق المستهدف"],
            sufficient=False,
            confidence=73,
        )
        first = build_feedback(state)
        second = build_feedback(state)
        self.assertEqual(first, second)

    def test_feedback_builder_does_not_mutate_state(self):
        state = state_for(resolved=4, missing=["Missing item"])
        before = json.loads(json.dumps(state, ensure_ascii=False))
        build_feedback(state)
        self.assertEqual(state, before)

    def test_feedback_contract_is_exact_and_json_safe(self):
        feedback = build_feedback(state_for())
        self.assertEqual(
            set(validate_feedback_contract(feedback)),
            {"understood_summary", "completion_percentage", "missing_information", "description_sufficient", "confidence_score"},
        )

    def test_builder_never_calls_provider(self):
        with patch("AI_Store_Creation_Service.providers.get_ai_provider_client") as provider:
            build_feedback(state_for(resolved=5))
        provider.assert_not_called()

    def test_node_only_builds_feedback_from_state(self):
        result = feedback_node(state_for(resolved=4))
        self.assertEqual(result["current_step"], "feedback")
        self.assertEqual(result["feedback"]["completion_percentage"], 40)

    def test_recoverable_failure_feedback(self):
        feedback = build_feedback({
            "understanding_valid": False,
            "description_language": "en",
            "effective_personalization_context": {},
            "missing_information": [],
            "description_sufficient": False,
            "confidence_score": 0,
        })
        self.assertEqual(feedback["completion_percentage"], 0)
        self.assertFalse(feedback["description_sufficient"])
        self.assertEqual(feedback["confidence_score"], 0)
