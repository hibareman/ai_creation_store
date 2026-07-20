import json
import unittest
from copy import deepcopy

from .agentic.clarifying import (
    AIClarificationValidationError,
    validate_clarification_questions_payload,
)
from .agentic.merging import AIMergeValidationError, merge_clarification_answers


def question(fact="target_audience", language="en", answer_type="single_select", recommendation=None):
    arabic = language == "ar"
    text = "من هم العملاء الأساسيون لمتجرك؟" if arabic else "Who are your primary customers?"
    reason = "يساعد ذلك في تخصيص المنتجات واللغة والتصميم." if arabic else "This helps tailor products, language, and design."
    other = "أخرى" if arabic else "Other"
    if answer_type == "free_text":
        options, other = [], None
    else:
        options = (["طلاب", "عائلات", "أخرى"] if arabic else ["Students", "Families", "Other"])
    return {
        "question_id": f"clarification_{fact}_1",
        "question_key": fact,
        "target_fact": fact,
        "question_text": text,
        "reason": reason,
        "recommendation": recommendation,
        "answer_type": answer_type,
        "options": options,
        "other_option": other,
        "allow_custom_answer": True,
        "required": True,
    }


class Phase4ClarificationTests(unittest.TestCase):
    def validate(self, q, fact="target_audience"):
        return validate_clarification_questions_payload(
            {"clarification_questions": [q]}, requested_question_keys=[fact],
            clarification_facts={}, clarification_history=[]
        )

    def test_canonical_target_fact_and_reason(self):
        result = self.validate(question())
        self.assertEqual(result[0]["target_fact"], "target_audience")
        self.assertTrue(result[0]["reason"])

    def test_unknown_target_fact_rejected(self):
        with self.assertRaises(AIClarificationValidationError):
            self.validate(question("unknown_fact"), "unknown_fact")

    def test_confirmed_and_previously_answered_rejected(self):
        q = question()
        with self.assertRaises(AIClarificationValidationError):
            validate_clarification_questions_payload(
                {"clarification_questions": [q]}, requested_question_keys=["target_audience"],
                clarification_facts={"target_audience": "Students"}, clarification_history=[]
            )

    def test_empty_question_and_reason_rejected(self):
        for field in ("question_text", "reason"):
            q = question(); q[field] = " "
            with self.assertRaises(AIClarificationValidationError): self.validate(q)

    def test_arabic_and_english_other_and_language(self):
        ar = self.validate(question(language="ar"))[0]
        en = self.validate(question(language="en"))[0]
        self.assertEqual(ar["options"][-1], "أخرى")
        self.assertEqual(en["options"][-1], "Other")
        self.assertIn("يساعد", ar["reason"])
        self.assertIn("helps", en["reason"])

    def test_duplicate_other_is_normalized_once(self):
        q = question(); q["options"] = ["Students", "Other", "Families", "Other"]
        result = self.validate(q)[0]
        self.assertEqual(result["options"].count("Other"), 1)
        self.assertEqual(result["options"][-1], "Other")

    def test_free_text_has_no_other(self):
        result = self.validate(question(answer_type="free_text"))[0]
        self.assertEqual(result["options"], [])
        self.assertIsNone(result["other_option"])

    def test_recommendation_string_or_null(self):
        self.assertIsNone(self.validate(question())[0]["recommendation"])
        self.assertEqual(self.validate(question(recommendation="You could focus on students."))[0]["recommendation"], "You could focus on students.")

    def test_recommendation_not_answer(self):
        q = self.validate(question(recommendation="Students may be a useful segment."))[0]
        merged = merge_clarification_answers(
            clarification_questions=[q],
            clarification_answers=[{"question_key":"target_audience","selected_option":"Families"}],
            clarification_history=[], clarification_facts={}, clarification_round_count=0,
        )
        self.assertEqual(merged["clarification_facts"]["target_audience"], "Families")

    def test_custom_other_answer_preserved_and_passed_to_context(self):
        q = self.validate(question())[0]
        custom = "Collectors interested in limited editions"
        merged = merge_clarification_answers(
            clarification_questions=[q],
            clarification_answers=[{"question_key":"target_audience","selected_option":"Other","custom_answer":custom}],
            clarification_history=[], clarification_facts={}, clarification_round_count=0,
        )
        self.assertEqual(merged["clarification_facts"]["target_audience"], custom)
        self.assertEqual(merged["clarification_history"][0]["answers"][0]["custom_answer"], custom)

    def test_json_serializable_and_deterministic(self):
        q = question()
        first = self.validate(deepcopy(q)); second = self.validate(deepcopy(q))
        self.assertEqual(first, second)
        json.dumps(first, ensure_ascii=False, allow_nan=False)

    def test_duplicate_target_rejected(self):
        q1=question(); q2=question(); q2["question_id"]="clarification_target_audience_2"; q2["question_text"]="Which customers matter most?"
        with self.assertRaises(AIClarificationValidationError):
            validate_clarification_questions_payload(
                {"clarification_questions":[q1,q2]},
                requested_question_keys=["target_audience","target_audience"], clarification_facts={}, clarification_history=[]
            )

    def test_round_limit_enforced(self):
        q = self.validate(question())[0]
        with self.assertRaises(AIMergeValidationError):
            merge_clarification_answers(
                clarification_questions=[q], clarification_answers=[{"question_key":"target_audience","selected_option":"Students"}],
                clarification_history=[], clarification_facts={}, clarification_round_count=3,
            )


if __name__ == "__main__": unittest.main()
