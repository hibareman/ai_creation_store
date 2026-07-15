"""Provider-backed clarification-question adapter for the agentic graph."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..constants import MAX_CLARIFICATION_ROUNDS
from ..exceptions import AIProviderParsingError
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from .merging import normalize_clarification_context


_TOP_LEVEL_KEYS = {"clarification_questions"}
_QUESTION_KEYS = {"question_key", "question_text", "options"}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_QUESTION_TEXT_LENGTH = 300
_MAX_OPTION_TEXT_LENGTH = 120
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
    business_summary: Any,
    target_audience: Any,
    product_direction: Any,
    blocking_missing_information: Any,
    ambiguities: Any,
    clarification_round_count: Any,
    clarification_history: Any = None,
    clarification_facts: Any = None,
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
    summary = _normalize_text(
        business_summary,
        field_name="business_summary",
        allow_empty=False,
        max_length=500,
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
    blocking_keys = _normalize_blocking_keys(blocking_missing_information)
    ambiguity_list = _normalize_string_list(
        ambiguities,
        field_name="ambiguities",
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
    semantic_analysis = {
        "description_language": language,
        "description_sufficient": False,
        "detected_store_domains": domains,
        "business_summary": summary,
        "target_audience": audience,
        "product_direction": products,
        "blocking_missing_information": blocking_keys,
        "ambiguities": ambiguity_list,
    }
    _assert_json_serializable(semantic_analysis)
    resolved_facts = clarification_context["clarification_facts"]
    if not set(blocking_keys).difference(resolved_facts):
        raise AIClarificationValidationError("No unresolved blocking keys remain.")

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
        blocking_missing_information=blocking_keys,
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
    blocking_missing_information: list[str],
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

    questions = payload_copy["clarification_questions"]
    if not isinstance(questions, list):
        raise AIClarificationValidationError("clarification_questions must be a list.")
    if not questions or len(questions) > 3:
        raise AIClarificationValidationError(
            "clarification_questions must contain 1 to 3 questions."
        )
    if len(questions) > len(blocking_missing_information):
        raise AIClarificationValidationError(
            "clarification_questions cannot exceed blocking missing information."
        )

    resolved_keys = set(clarification_facts or {})
    blocking_keys = set(blocking_missing_information).difference(resolved_keys)
    previous_question_texts = _previous_question_texts(clarification_history or [])
    normalized_questions: list[dict[str, Any]] = []
    seen_question_keys: set[str] = set()
    seen_question_texts: set[str] = set()
    for question in questions:
        if not isinstance(question, Mapping):
            raise AIClarificationValidationError("Each question must be an object.")
        question_copy = dict(deepcopy(question))
        if set(question_copy) != _QUESTION_KEYS:
            raise AIClarificationValidationError(
                "Each question must contain exact keys."
            )

        question_key = _normalize_question_key(question_copy["question_key"])
        if question_key in _OPTIONAL_QUESTION_KEYS:
            raise AIClarificationValidationError(
                "Clarification questions cannot ask optional defaults."
            )
        if question_key in resolved_keys:
            raise AIClarificationValidationError(
                "Clarification questions cannot repeat resolved keys."
            )
        if question_key not in blocking_keys:
            raise AIClarificationValidationError(
                "question_key must be part of blocking_missing_information."
            )
        if question_key in seen_question_keys:
            raise AIClarificationValidationError("question_key values must be unique.")
        seen_question_keys.add(question_key)

        question_text = _normalize_text(
            question_copy["question_text"],
            field_name="question_text",
            allow_empty=False,
            max_length=_MAX_QUESTION_TEXT_LENGTH,
        )
        question_text_key = question_text.casefold()
        if question_text_key in previous_question_texts:
            raise AIClarificationValidationError(
                "Clarification questions cannot repeat previous question text."
            )
        if question_text_key in seen_question_texts:
            raise AIClarificationValidationError(
                "question_text values must be unique."
            )
        seen_question_texts.add(question_text_key)

        normalized_questions.append(
            {
                "question_key": question_key,
                "question_text": question_text,
                "options": _normalize_options(question_copy["options"]),
            }
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


def _normalize_blocking_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AIClarificationValidationError(
            "blocking_missing_information must be a list."
        )
    if not value or len(value) > 5:
        raise AIClarificationValidationError(
            "blocking_missing_information must contain 1 to 5 keys."
        )

    normalized_keys: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = _normalize_question_key(item)
        if key in seen:
            raise AIClarificationValidationError(
                "blocking_missing_information must be unique."
            )
        seen.add(key)
        normalized_keys.append(key)
    return normalized_keys


def _normalize_question_key(value: Any) -> str:
    if not isinstance(value, str):
        raise AIClarificationValidationError("question_key must be a string.")
    normalized = value.strip()
    if not _SNAKE_CASE_RE.fullmatch(normalized):
        raise AIClarificationValidationError("question_key must be snake_case.")
    return normalized


def _normalize_options(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AIClarificationValidationError("options must be a list.")
    if len(value) < 2 or len(value) > 5:
        raise AIClarificationValidationError("options must contain 2 to 5 items.")

    normalized_options: list[str] = []
    seen: set[str] = set()
    for option in value:
        normalized = _normalize_text(
            option,
            field_name="option",
            allow_empty=False,
            max_length=_MAX_OPTION_TEXT_LENGTH,
        )
        key = normalized.casefold()
        if key in seen:
            raise AIClarificationValidationError("options must be unique.")
        seen.add(key)
        normalized_options.append(normalized)
    return normalized_options


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


__all__ = [
    "AIClarificationValidationError",
    "generate_clarification_questions",
    "validate_clarification_questions_payload",
]
