"""Provider-backed clarification-question adapter for the agentic graph."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..constants import (
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
)
from ..exceptions import AIProviderParsingError
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from .merging import normalize_clarification_context
from .personalization import CORE_PERSONALIZATION_KEYS


_TOP_LEVEL_KEYS = {"clarification_questions"}
_QUESTION_KEYS = {
    "question_id", "question_key", "target_fact", "question_text", "reason",
    "recommendation", "answer_type", "options", "other_option",
    "allow_custom_answer", "required",
}
_SPEC_KEYS = {"question_key", "purpose", "question_type"}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_QUESTION_TEXT_LENGTH = 300
_MAX_OPTION_TEXT_LENGTH = 120
_MAX_REASON_TEXT_LENGTH = 240
_MAX_RECOMMENDATION_TEXT_LENGTH = 300
_OPTIONAL_QUESTION_KEYS = {
    "store_name",
    "currency",
    "timezone",
    "logo",
    "logo_url",
    "banner",
    "banner_url",
    "font",
    "font_family",
    "primary_color",
    "secondary_color",
    "exact_product_count",
    "exact_category_names",
    "exact_product_names",
    "prices",
    "stock",
    "image_urls",
}


class AIClarificationValidationError(ValueError):
    """Raised when clarification input or provider output is unsafe."""


def generate_clarification_questions(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    normalized_description: Any,
    description_language: Any,
    detected_store_domains: Any,
    target_audience: Any,
    product_direction: Any,
    blocking_missing_information: Any,
    ambiguities: Any,
    clarification_round_count: Any,
    clarification_history: Any = None,
    clarification_facts: Any = None,
    requested_question_keys: Any = None,
    requested_question_specs: Any = None,
    effective_personalization_context: Any = None,
) -> list[dict[str, Any]]:
    normalized_store_id = _validate_positive_int(store_id)
    normalized_tenant_id = _validate_positive_int(tenant_id)
    _validate_positive_int(user_id)
    description = _validate_normalized_description(normalized_description)
    language = _validate_language(description_language)
    domains = _normalize_string_list(
        detected_store_domains,
        field_name="detected_store_domains",
        max_items=3,
        allow_empty=True,
        max_text_length=300,
    )
    audience = _normalize_text(
        target_audience,
        field_name="target_audience",
        allow_empty=True,
        max_length=300,
    )
    products = _normalize_string_list(
        product_direction,
        field_name="product_direction",
        max_items=5,
        allow_empty=True,
        max_text_length=300,
    )
    round_count = _validate_round_count(clarification_round_count)
    clarification_context = normalize_clarification_context(
        clarification_history=[] if clarification_history is None else clarification_history,
        clarification_facts={} if clarification_facts is None else clarification_facts,
        clarification_round_count=round_count,
    )
    resolved_facts = clarification_context["clarification_facts"]
    requested_keys = _normalize_requested_keys(
        requested_question_keys
        if requested_question_keys is not None
        else blocking_missing_information
    )
    requested_specs = _normalize_requested_specs(
        requested_question_specs,
        requested_keys=requested_keys,
    )
    previous_keys = _previous_question_keys(
        clarification_context["clarification_history"]
    )
    if set(requested_keys).intersection(resolved_facts):
        raise AIClarificationValidationError(
            "Requested questions cannot repeat resolved clarification facts."
        )
    if set(requested_keys).intersection(previous_keys):
        raise AIClarificationValidationError(
            "Requested questions cannot repeat previously asked keys."
        )

    ambiguity_list = _normalize_string_list(
        ambiguities,
        field_name="ambiguities",
        max_items=5,
        allow_empty=True,
        max_text_length=300,
    )
    personalization_context = _normalize_json_mapping(
        effective_personalization_context,
        field_name="effective_personalization_context",
    )
    semantic_analysis = {
        "description_language": language,
        "description_sufficient": False,
        "detected_store_domains": domains,
        "target_audience": audience,
        "product_direction": products,
        "blocking_missing_information": requested_keys,
        "ambiguities": ambiguity_list,
        "requested_question_keys": requested_keys,
        "requested_question_specs": requested_specs,
        "effective_personalization_context": personalization_context,
    }
    _assert_json_serializable(semantic_analysis)

    provider = get_ai_provider_client()

    def provider_call() -> dict[str, Any]:
        return provider.generate_clarification_questions(
            tenant_id=normalized_tenant_id,
            store_id=normalized_store_id,
            normalized_description=description,
            semantic_analysis=deepcopy(semantic_analysis),
            clarification_round_count=round_count,
            clarification_context=deepcopy(clarification_context),
        )

    parsed_payload = _parse_provider_response_with_single_retry(provider_call)
    questions = validate_clarification_questions_payload(
        parsed_payload,
        requested_question_keys=requested_keys,
        blocking_missing_information=requested_keys,
        clarification_facts=resolved_facts,
        clarification_history=clarification_context["clarification_history"],
    )
    return _json_defensive_copy(questions)


def _parse_provider_response_with_single_retry(
    provider_call: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError:
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def validate_clarification_questions_payload(
    payload: Any,
    *,
    requested_question_keys: list[str] | None = None,
    blocking_missing_information: list[str] | None = None,
    clarification_facts: Mapping[str, str] | None = None,
    clarification_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise AIClarificationValidationError("Clarification payload must be an object.")
    payload_copy = dict(deepcopy(payload))
    _assert_json_serializable(payload_copy)
    if set(payload_copy) != _TOP_LEVEL_KEYS:
        raise AIClarificationValidationError(
            "Clarification payload must contain only clarification_questions."
        )

    expected_keys = _normalize_requested_keys(
        requested_question_keys
        if requested_question_keys is not None
        else blocking_missing_information
    )
    questions = payload_copy["clarification_questions"]
    if not isinstance(questions, list):
        raise AIClarificationValidationError("clarification_questions must be a list.")
    if len(questions) != len(expected_keys):
        raise AIClarificationValidationError(
            "The provider must return exactly the requested clarification questions."
        )
    if not questions or len(questions) > MAX_CLARIFICATION_QUESTIONS_PER_ROUND:
        raise AIClarificationValidationError(
            "clarification_questions must contain 1 to 5 questions."
        )

    resolved_keys = set(clarification_facts or {})
    previous_keys = _previous_question_keys(clarification_history or [])
    previous_question_texts = _previous_question_texts(clarification_history or [])
    normalized_questions: list[dict[str, Any]] = []
    seen_question_keys: set[str] = set()
    seen_question_ids: set[str] = set()
    seen_question_texts: set[str] = set()

    for index, question in enumerate(questions):
        if not isinstance(question, Mapping):
            raise AIClarificationValidationError("Each question must be an object.")
        question_copy = dict(deepcopy(question))
        if set(question_copy) != _QUESTION_KEYS:
            raise AIClarificationValidationError("Each question must contain the exact Phase 4 keys.")

        question_key = _normalize_question_key(question_copy["question_key"])
        target_fact = _normalize_question_key(question_copy["target_fact"])
        expected_key = expected_keys[index]
        if question_key != expected_key or target_fact != expected_key:
            raise AIClarificationValidationError(
                "question_key and target_fact must exactly match the requested canonical fact order."
            )
        if target_fact not in CORE_PERSONALIZATION_KEYS:
            raise AIClarificationValidationError("target_fact must be canonical.")
        if target_fact in resolved_keys or target_fact in previous_keys:
            raise AIClarificationValidationError("Resolved or previously asked facts cannot be questioned.")
        if target_fact in seen_question_keys:
            raise AIClarificationValidationError("target_fact values must be unique within a round.")
        seen_question_keys.add(target_fact)

        question_id = _normalize_question_id(question_copy["question_id"])
        expected_prefix = f"clarification_{target_fact}_"
        if not question_id.startswith(expected_prefix):
            raise AIClarificationValidationError("question_id must be stable and linked to target_fact.")
        if question_id in seen_question_ids:
            raise AIClarificationValidationError("question_id values must be unique.")
        seen_question_ids.add(question_id)

        question_text = _normalize_text(
            question_copy["question_text"], field_name="question_text",
            allow_empty=False, max_length=_MAX_QUESTION_TEXT_LENGTH,
        )
        question_text_key = question_text.casefold()
        if question_text_key in previous_question_texts or question_text_key in seen_question_texts:
            raise AIClarificationValidationError("Question text must not be duplicated.")
        seen_question_texts.add(question_text_key)

        reason = _normalize_text(
            question_copy["reason"], field_name="reason", allow_empty=False,
            max_length=_MAX_REASON_TEXT_LENGTH,
        )
        recommendation = question_copy["recommendation"]
        if recommendation is not None:
            recommendation = _normalize_text(
                recommendation, field_name="recommendation", allow_empty=False,
                max_length=_MAX_RECOMMENDATION_TEXT_LENGTH,
            )

        answer_type = question_copy["answer_type"]
        if answer_type not in {"single_select", "free_text"}:
            raise AIClarificationValidationError("answer_type is invalid.")
        if question_copy["required"] is not True:
            raise AIClarificationValidationError("required must be true.")
        allow_custom_answer = question_copy["allow_custom_answer"]
        if not isinstance(allow_custom_answer, bool):
            raise AIClarificationValidationError("allow_custom_answer must be boolean.")

        if answer_type == "single_select":
            if allow_custom_answer is not True:
                raise AIClarificationValidationError("Selectable questions must allow a custom answer.")
            other_option = _normalize_text(
                question_copy["other_option"], field_name="other_option",
                allow_empty=False, max_length=_MAX_OPTION_TEXT_LENGTH,
            )
            expected_other = "أخرى" if _looks_arabic(question_text) else "Other"
            if other_option != expected_other:
                raise AIClarificationValidationError("other_option must preserve the question language.")
            options = _normalize_options_with_other(question_copy["options"], other_option=other_option)
        else:
            if question_copy["options"] != [] or question_copy["other_option"] is not None:
                raise AIClarificationValidationError("Free-text questions must not contain options or Other.")
            options = []
            other_option = None
            if allow_custom_answer is not True:
                raise AIClarificationValidationError("Free-text questions must accept custom input.")

        normalized_questions.append({
            "question_id": question_id,
            "question_key": question_key,
            "target_fact": target_fact,
            "question_text": question_text,
            "reason": reason,
            "recommendation": recommendation,
            "answer_type": answer_type,
            "options": options,
            "other_option": other_option,
            "allow_custom_answer": allow_custom_answer,
            "required": True,
        })

    if [question["question_key"] for question in normalized_questions] != expected_keys:
        raise AIClarificationValidationError(
            "Clarification questions must exactly match requested keys."
        )
    _assert_json_serializable(normalized_questions)
    return normalized_questions


def _validate_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AIClarificationValidationError("Identity values must be positive integers.")
    return value


def _validate_normalized_description(value: Any) -> str:
    if not isinstance(value, str):
        raise AIClarificationValidationError("normalized_description must be a string.")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise AIClarificationValidationError("normalized_description is required.")
    return normalized


def _validate_language(value: Any) -> str:
    if value not in {"ar", "en", "unknown"}:
        raise AIClarificationValidationError("description_language is invalid.")
    return value


def _validate_round_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AIClarificationValidationError(
            "clarification_round_count must be an integer."
        )
    if value < 0 or value >= MAX_CLARIFICATION_ROUNDS:
        raise AIClarificationValidationError(
            "clarification_round_count is outside the allowed range."
        )
    return value


def _normalize_text(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise AIClarificationValidationError(f"{field_name} must be a string.")
    normalized = " ".join(value.strip().split())
    if not normalized and not allow_empty:
        raise AIClarificationValidationError(f"{field_name} must be non-empty.")
    if len(normalized) > max_length:
        raise AIClarificationValidationError(f"{field_name} is too long.")
    return normalized


def _normalize_string_list(
    value: Any,
    *,
    field_name: str,
    max_items: int,
    allow_empty: bool,
    max_text_length: int,
) -> list[str]:
    if not isinstance(value, list):
        raise AIClarificationValidationError(f"{field_name} must be a list.")
    if len(value) > max_items:
        raise AIClarificationValidationError(f"{field_name} has too many items.")

    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _normalize_text(
            item,
            field_name=field_name,
            allow_empty=False,
            max_length=max_text_length,
        )
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_items.append(normalized)
    if not allow_empty and not normalized_items:
        raise AIClarificationValidationError(f"{field_name} must be non-empty.")
    return normalized_items


def _normalize_requested_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AIClarificationValidationError(
            "requested_question_keys must be a list."
        )
    if not value or len(value) > MAX_CLARIFICATION_QUESTIONS_PER_ROUND:
        raise AIClarificationValidationError(
            "requested_question_keys must contain 1 to 5 keys."
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = _normalize_question_key(item)
        if key not in CORE_PERSONALIZATION_KEYS:
            raise AIClarificationValidationError(
                "requested_question_keys must contain canonical personalization keys only."
            )
        if key in seen:
            raise AIClarificationValidationError(
                "requested_question_keys must be unique."
            )
        seen.add(key)
        normalized.append(key)
    return normalized


def _normalize_requested_specs(
    value: Any,
    *,
    requested_keys: list[str],
) -> list[dict[str, str]]:
    if value is None:
        return [
            {
                "question_key": key,
                "purpose": (
                    f"Collect the confirmed personalization fact for {key}."
                    if key in CORE_PERSONALIZATION_KEYS
                    else f"Resolve the blocking store decision represented by {key}."
                ),
                "question_type": (
                    "core" if key in CORE_PERSONALIZATION_KEYS else "adaptive"
                ),
            }
            for key in requested_keys
        ]
    if not isinstance(value, list) or len(value) != len(requested_keys):
        raise AIClarificationValidationError(
            "requested_question_specs must match requested_question_keys."
        )
    normalized: list[dict[str, str]] = []
    for index, spec in enumerate(value):
        if not isinstance(spec, Mapping) or set(spec) != _SPEC_KEYS:
            raise AIClarificationValidationError(
                "Each requested question spec must match the schema."
            )
        key = _normalize_question_key(spec["question_key"])
        if key != requested_keys[index]:
            raise AIClarificationValidationError(
                "requested_question_specs must preserve requested key order."
            )
        purpose = _normalize_text(
            spec["purpose"],
            field_name="purpose",
            allow_empty=False,
            max_length=300,
        )
        question_type = spec["question_type"]
        if question_type not in {"core", "adaptive"}:
            raise AIClarificationValidationError("question_type is invalid.")
        normalized.append(
            {
                "question_key": key,
                "purpose": purpose,
                "question_type": question_type,
            }
        )
    return normalized


def _normalize_question_key(value: Any) -> str:
    if not isinstance(value, str):
        raise AIClarificationValidationError("question_key must be a string.")
    normalized = value.strip()
    if not _SNAKE_CASE_RE.fullmatch(normalized):
        raise AIClarificationValidationError("question_key must be snake_case.")
    return normalized


def _normalize_question_id(value: Any) -> str:
    if not isinstance(value, str):
        raise AIClarificationValidationError("question_id must be a string.")
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise AIClarificationValidationError("question_id is invalid.")
    return normalized


def _looks_arabic(value: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in value)


def _normalize_options_with_other(value: Any, *, other_option: str) -> list[str]:
    if not isinstance(value, list) or len(value) < 2 or len(value) > 5:
        raise AIClarificationValidationError("options must contain 2 to 5 items before normalization.")
    normalized: list[str] = []
    seen: set[str] = set()
    other_aliases = {"other", "أخرى"}
    for option in value:
        text = _normalize_text(option, field_name="option", allow_empty=False, max_length=_MAX_OPTION_TEXT_LENGTH)
        key = _normalize_option_value(text)
        if key in other_aliases:
            continue
        if key in seen:
            raise AIClarificationValidationError("options must be unique.")
        seen.add(key)
        normalized.append(text)
    if len(normalized) < 2 or len(normalized) > 4:
        raise AIClarificationValidationError("Selectable questions require 2 to 4 predefined choices.")
    normalized.append(other_option)
    return normalized


def _normalize_options(value: Any, *, other_option: str) -> list[str]:
    if not isinstance(value, list):
        raise AIClarificationValidationError("options must be a list.")
    if len(value) < 3 or len(value) > 5:
        raise AIClarificationValidationError("options must contain 3 to 5 items.")

    normalized_options: list[str] = []
    seen: set[str] = set()
    for option in value:
        normalized = _normalize_text(
            option,
            field_name="option",
            allow_empty=False,
            max_length=_MAX_OPTION_TEXT_LENGTH,
        )
        key = _normalize_option_value(normalized)
        if key in seen:
            raise AIClarificationValidationError("options must be unique.")
        seen.add(key)
        normalized_options.append(normalized)

    other_key = _normalize_option_value(other_option)
    matching_count = sum(
        1 for option in normalized_options if _normalize_option_value(option) == other_key
    )
    if matching_count != 1:
        raise AIClarificationValidationError(
            "other_option must match exactly one available option."
        )
    if _normalize_option_value(normalized_options[-1]) != other_key:
        raise AIClarificationValidationError(
            "other_option must be the final option."
        )
    return normalized_options


def _normalize_option_value(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _normalize_json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AIClarificationValidationError(f"{field_name} must be an object.")
    copied = dict(deepcopy(value))
    _assert_json_serializable(copied)
    return copied


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def _json_defensive_copy(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _previous_question_texts(history: list[dict[str, Any]]) -> set[str]:
    texts: set[str] = set()
    for round_item in history:
        for question in round_item.get("questions", []):
            question_text = question.get("question_text")
            if isinstance(question_text, str):
                texts.add(" ".join(question_text.strip().split()).casefold())
    return texts


def _previous_question_keys(history: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for round_item in history:
        for question in round_item.get("questions", []):
            question_key = question.get("question_key")
            if isinstance(question_key, str):
                normalized = question_key.strip()
                if _SNAKE_CASE_RE.fullmatch(normalized):
                    keys.add(normalized)
    return keys


__all__ = [
    "AIClarificationValidationError",
    "generate_clarification_questions",
    "validate_clarification_questions_payload",
]
