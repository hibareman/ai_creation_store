"""Deterministic clarification-answer merging for the agentic graph."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .personalization import CORE_PERSONALIZATION_KEYS

from ..constants import (
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
)


_QUESTION_KEYS = {
    "question_id", "question_key", "target_fact", "question_text", "reason",
    "recommendation", "answer_type", "options", "other_option",
    "allow_custom_answer", "required",
}
_LEGACY_QUESTION_KEYS = {"question_key", "question_text", "options"}
_ANSWER_KEYS = {"question_key", "selected_option"}
_ANSWER_KEYS_WITH_CUSTOM = {"question_key", "selected_option", "custom_answer"}
_ROUND_KEYS = {"round_number", "questions", "answers", "resolved_facts"}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_TEXT_LENGTH = 300
_MAX_OPTION_LENGTH = 120
_MIN_OPTION_COUNT = 3
_LEGACY_MIN_OPTION_COUNT = 2


class AIMergeValidationError(ValueError):
    """Raised when clarification resume input is malformed or unsafe."""


def merge_clarification_answers(
    *,
    clarification_questions: Any,
    clarification_answers: Any,
    clarification_history: Any,
    clarification_facts: Any,
    clarification_round_count: Any,
    previous_confirmed_context: Any = None,
    latest_ai_context: Any = None,
) -> dict[str, Any]:
    round_count = _validate_merge_round_count(clarification_round_count)
    questions = normalize_clarification_questions(clarification_questions)
    history, derived_facts = normalize_clarification_history(
        clarification_history,
        expected_round_count=round_count,
    )
    facts = normalize_clarification_facts(clarification_facts)
    if facts != derived_facts:
        raise AIMergeValidationError("clarification_facts must match history.")

    answers = validate_clarification_answer_submission(
        clarification_questions=questions,
        clarification_answers=clarification_answers,
    )
    resolved_facts = _facts_from_answers(answers)
    new_count = round_count + 1
    new_history = [
        *history,
        {
            "round_number": new_count,
            "questions": _json_defensive_copy(questions),
            "answers": _json_defensive_copy(answers),
            "resolved_facts": _json_defensive_copy(resolved_facts),
        },
    ]
    new_facts = {**facts, **resolved_facts}
    previous_confirmed = normalize_previous_confirmed_context(
        {} if previous_confirmed_context is None else previous_confirmed_context
    )
    ai_understood = normalize_previous_confirmed_context(
        {} if latest_ai_context is None else latest_ai_context
    )

    # Strict context separation:
    # - AI-understood values remain available only in the merged context.
    # - Confirmed context contains explicit merchant answers only.
    # - Latest answers override previous merchant confirmations, which override AI values.
    confirmed_context = {**previous_confirmed, **resolved_facts}
    merged_context = {**ai_understood, **confirmed_context}
    output = {
        "clarification_round_count": new_count,
        "clarification_history": new_history,
        "clarification_facts": new_facts,
        "merged_personalization_context": merged_context,
        "confirmed_personalization_context": confirmed_context,
        "answered_target_facts": sorted(confirmed_context),
        "canonical_answers": answers,
    }
    return _json_defensive_copy(output)


def validate_clarification_answer_submission(
    *,
    clarification_questions: Any,
    clarification_answers: Any,
) -> list[dict[str, Any]]:
    questions = normalize_clarification_questions(clarification_questions)
    answers = normalize_clarification_answers(
        clarification_answers,
        questions=questions,
    )
    return _json_defensive_copy(answers)


def normalize_clarification_context(
    *,
    clarification_history: Any,
    clarification_facts: Any,
    clarification_round_count: Any,
) -> dict[str, Any]:
    round_count = _validate_context_round_count(clarification_round_count)
    history, derived_facts = normalize_clarification_history(
        clarification_history,
        expected_round_count=round_count,
    )
    facts = normalize_clarification_facts(clarification_facts)
    if facts != derived_facts:
        raise AIMergeValidationError("clarification_facts must match history.")
    return _json_defensive_copy(
        {
            "clarification_round_count": round_count,
            "clarification_history": history,
            "clarification_facts": facts,
        }
    )


def normalize_clarification_questions(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_CLARIFICATION_QUESTIONS_PER_ROUND
    ):
        raise AIMergeValidationError("clarification_questions must contain 1 to 5 items.")
    _assert_json_serializable(value)

    normalized_questions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for question in value:
        if not isinstance(question, Mapping):
            raise AIMergeValidationError("Each clarification question must match the schema.")
        if set(question) == _QUESTION_KEYS:
            question_key = _normalize_identifier(question["question_key"])
            target_fact = _normalize_identifier(question["target_fact"])
            if question_key != target_fact:
                raise AIMergeValidationError("question_key must match target_fact.")
            if target_fact not in CORE_PERSONALIZATION_KEYS:
                raise AIMergeValidationError("target_fact must be canonical.")
            question_text = _normalize_text(question["question_text"], max_length=_MAX_TEXT_LENGTH)
            reason = _normalize_text(question["reason"], max_length=_MAX_TEXT_LENGTH)
            recommendation = question["recommendation"]
            if recommendation is not None:
                recommendation = _normalize_text(recommendation, max_length=_MAX_TEXT_LENGTH)
            answer_type = question["answer_type"]
            if answer_type not in {"single_select", "free_text"}:
                raise AIMergeValidationError("answer_type is invalid.")
            if answer_type == "single_select":
                other_option = _normalize_text(question["other_option"], max_length=_MAX_OPTION_LENGTH)
                options = _normalize_options(question["options"], min_count=3, other_option=other_option)
            else:
                if question["options"] != [] or question["other_option"] is not None:
                    raise AIMergeValidationError("Free-text questions cannot contain options.")
                options, other_option = [], None
            if question["allow_custom_answer"] is not True or question["required"] is not True:
                raise AIMergeValidationError("Clarification input flags are invalid.")
            normalized_question = {
                "question_id": _normalize_text(question["question_id"], max_length=120),
                "question_key": question_key,
                "target_fact": target_fact,
                "question_text": question_text,
                "reason": reason,
                "recommendation": recommendation,
                "answer_type": answer_type,
                "options": options,
                "other_option": other_option,
                "allow_custom_answer": True,
                "required": True,
            }
        elif set(question) == _LEGACY_QUESTION_KEYS:
            question_key = _normalize_identifier(question["question_key"])
            question_text = _normalize_text(question["question_text"], max_length=_MAX_TEXT_LENGTH)
            options = _normalize_options(
                question["options"],
                min_count=_LEGACY_MIN_OPTION_COUNT,
                other_option=None,
            )
            normalized_question = {
                "question_key": question_key,
                "question_text": question_text,
                "options": options,
            }
        else:
            raise AIMergeValidationError("Each clarification question must match the schema.")

        if question_key in seen_keys:
            raise AIMergeValidationError("question_key values must be unique.")
        seen_keys.add(question_key)
        normalized_questions.append(normalized_question)
    return _json_defensive_copy(normalized_questions)


def normalize_clarification_answers(
    value: Any,
    *,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise AIMergeValidationError("clarification_answers must be a non-empty list.")
    if len(value) != len(questions):
        raise AIMergeValidationError("All pending clarification questions must be answered.")
    _assert_json_serializable(value)

    question_by_key = {question["question_key"]: question for question in questions}
    pending_keys = set(question_by_key)
    normalized_answers: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for answer in value:
        if not isinstance(answer, Mapping):
            raise AIMergeValidationError("Each clarification answer must match the schema.")
        answer_keys = set(answer)
        if answer_keys not in {frozenset(_ANSWER_KEYS), frozenset(_ANSWER_KEYS_WITH_CUSTOM)}:
            raise AIMergeValidationError("Each clarification answer must match the schema.")

        question_key = _normalize_identifier(answer["question_key"])
        if question_key in seen_keys:
            raise AIMergeValidationError("question_key answers must be unique.")
        if question_key not in pending_keys:
            raise AIMergeValidationError("Answer question_key is not pending.")
        seen_keys.add(question_key)

        question = question_by_key[question_key]
        if question.get("answer_type") == "free_text":
            raw_value = answer.get("custom_answer", answer.get("selected_option"))
            custom_answer = _normalize_custom_answer(raw_value)
            normalized_answers.append({
                "question_key": question_key,
                "selected_option": custom_answer,
                "custom_answer": custom_answer,
            })
            continue
        selected_option = _canonicalize_selected_option(
            answer["selected_option"],
            options=question["options"],
        )
        other_option = question.get("other_option")
        is_other_selection = bool(
            other_option and _normalize_option_value(selected_option) == _normalize_option_value(other_option)
        )

        if is_other_selection:
            if "custom_answer" not in answer:
                raise AIMergeValidationError("custom_answer is required when Other is selected.")
            custom_answer = _normalize_custom_answer(answer["custom_answer"])
            normalized_answers.append(
                {
                    "question_key": question_key,
                    "selected_option": selected_option,
                    "custom_answer": custom_answer,
                }
            )
            continue

        if "custom_answer" in answer:
            raise AIMergeValidationError("custom_answer is only allowed when Other is selected.")

        normalized_answers.append(
            {
                "question_key": question_key,
                "selected_option": selected_option,
            }
        )

    if seen_keys != pending_keys:
        raise AIMergeValidationError("Answer keys must match pending question keys.")
    return _json_defensive_copy(normalized_answers)


def normalize_clarification_history(
    value: Any,
    *,
    expected_round_count: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not isinstance(value, list):
        raise AIMergeValidationError("clarification_history must be a list.")
    if len(value) != expected_round_count:
        raise AIMergeValidationError("clarification_history length must match the counter.")
    if len(value) > MAX_CLARIFICATION_ROUNDS:
        raise AIMergeValidationError("clarification_history is too long.")
    _assert_json_serializable(value)

    normalized_history: list[dict[str, Any]] = []
    derived_facts: dict[str, str] = {}
    for expected_round_number, round_item in enumerate(value, start=1):
        if not isinstance(round_item, Mapping) or set(round_item) != _ROUND_KEYS:
            raise AIMergeValidationError("Each clarification round must match the schema.")
        round_number = round_item["round_number"]
        if (
            isinstance(round_number, bool)
            or not isinstance(round_number, int)
            or round_number != expected_round_number
        ):
            raise AIMergeValidationError("round_number values must be sequential.")
        questions = normalize_clarification_questions(round_item["questions"])
        answers = normalize_clarification_answers(
            round_item["answers"],
            questions=questions,
        )
        resolved_facts = _facts_from_answers(answers)
        normalized_round_facts = normalize_clarification_facts(
            round_item["resolved_facts"]
        )
        if normalized_round_facts != resolved_facts:
            raise AIMergeValidationError("resolved_facts must match round answers.")
        derived_facts.update(resolved_facts)
        normalized_history.append(
            {
                "round_number": round_number,
                "questions": questions,
                "answers": answers,
                "resolved_facts": resolved_facts,
            }
        )
    return _json_defensive_copy(normalized_history), _json_defensive_copy(derived_facts)


def normalize_previous_confirmed_context(value: Any) -> dict[str, str]:
    """Validate prior confirmed canonical context without deriving new meaning."""
    if not isinstance(value, Mapping):
        raise AIMergeValidationError("previous_confirmed_context must be an object.")
    _assert_json_serializable(dict(value))
    normalized: dict[str, str] = {}
    for key, fact_value in value.items():
        normalized_key = _normalize_identifier(key)
        if normalized_key not in CORE_PERSONALIZATION_KEYS:
            continue
        if not isinstance(fact_value, str) or not fact_value.strip():
            continue
        if len(fact_value) > _MAX_TEXT_LENGTH:
            raise AIMergeValidationError("previous confirmed value is too long.")
        normalized[normalized_key] = fact_value
    return _json_defensive_copy(normalized)


def normalize_clarification_facts(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise AIMergeValidationError("clarification_facts must be an object.")
    if len(value) > MAX_CLARIFICATION_ROUNDS * MAX_CLARIFICATION_QUESTIONS_PER_ROUND:
        raise AIMergeValidationError("clarification_facts has too many items.")
    _assert_json_serializable(dict(value))

    normalized_facts: dict[str, str] = {}
    for key, fact_value in value.items():
        normalized_key = _normalize_identifier(key)
        if normalized_key not in CORE_PERSONALIZATION_KEYS:
            raise AIMergeValidationError("clarification_facts keys must be canonical.")
        normalized_facts[normalized_key] = _preserve_answer_text(
            fact_value,
            max_length=_MAX_TEXT_LENGTH,
        )
    return _json_defensive_copy(normalized_facts)


def _validate_merge_round_count(value: Any) -> int:
    round_count = _validate_context_round_count(value)
    if round_count >= MAX_CLARIFICATION_ROUNDS:
        raise AIMergeValidationError("Clarification round limit has been reached.")
    return round_count


def _validate_context_round_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AIMergeValidationError("clarification_round_count must be an integer.")
    if value < 0 or value > MAX_CLARIFICATION_ROUNDS:
        raise AIMergeValidationError("clarification_round_count is outside the limit.")
    return value


def _normalize_identifier(value: Any) -> str:
    if not isinstance(value, str):
        raise AIMergeValidationError("Identifier values must be strings.")
    normalized = value.strip()
    if not _SNAKE_CASE_RE.fullmatch(normalized):
        raise AIMergeValidationError("Identifier values must be snake_case.")
    return normalized


def _normalize_text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise AIMergeValidationError("Text values must be strings.")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise AIMergeValidationError("Text values must be non-empty.")
    if len(normalized) > max_length:
        raise AIMergeValidationError("Text value is too long.")
    return normalized


def _preserve_answer_text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise AIMergeValidationError("Answer values must be strings.")
    if not value.strip():
        raise AIMergeValidationError("Answer values must be non-empty.")
    if len(value) > max_length:
        raise AIMergeValidationError("Answer value is too long.")
    return value


def _normalize_custom_answer(value: Any) -> str:
    """Validate merchant wording without rewriting or semantic normalization."""
    if not isinstance(value, str):
        raise AIMergeValidationError("custom_answer must be a string.")
    if not value.strip():
        raise AIMergeValidationError("custom_answer must be non-empty.")
    if len(value) > _MAX_TEXT_LENGTH:
        raise AIMergeValidationError("custom_answer must not exceed 300 characters.")
    return value


def _normalize_options(value: Any, *, min_count: int, other_option: str | None) -> list[str]:
    if not isinstance(value, list) or len(value) < min_count or len(value) > 5:
        raise AIMergeValidationError("options must contain the required number of values.")
    normalized_options: list[str] = []
    seen: set[str] = set()
    for option in value:
        normalized = _normalize_text(option, max_length=_MAX_OPTION_LENGTH)
        key = normalized.casefold()
        if key in seen:
            raise AIMergeValidationError("options must be unique.")
        seen.add(key)
        normalized_options.append(normalized)

    if other_option is not None:
        normalized_other = _normalize_text(other_option, max_length=_MAX_OPTION_LENGTH)
        if _normalize_option_value(normalized_other) not in {
            _normalize_option_value(option) for option in normalized_options
        }:
            raise AIMergeValidationError("other_option must match one available option.")
        if _normalize_option_value(normalized_options[-1]) != _normalize_option_value(normalized_other):
            raise AIMergeValidationError("other_option must be the final option.")
    return normalized_options


def _normalize_option_value(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _canonicalize_selected_option(value: Any, *, options: list[str]) -> str:
    selected = _normalize_text(value, max_length=_MAX_OPTION_LENGTH)
    selected_key = _normalize_option_value(selected)
    for option in options:
        if _normalize_option_value(option) == selected_key:
            return option
    raise AIMergeValidationError("selected_option must match one available option.")


def _facts_from_answers(answers: list[dict[str, Any]]) -> dict[str, str]:
    resolved_facts: dict[str, str] = {}
    for answer in answers:
        if "custom_answer" in answer and isinstance(answer["custom_answer"], str):
            resolved_facts[answer["question_key"]] = answer["custom_answer"]
        else:
            resolved_facts[answer["question_key"]] = answer["selected_option"]
    return resolved_facts


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


__all__ = [
    "AIMergeValidationError",
    "merge_clarification_answers",
    "normalize_clarification_answers",
    "normalize_clarification_context",
    "normalize_clarification_facts",
    "normalize_clarification_history",
    "normalize_clarification_questions",
    "normalize_previous_confirmed_context",
    "validate_clarification_answer_submission",
]
