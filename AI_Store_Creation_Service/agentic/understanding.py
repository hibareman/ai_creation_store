"""Provider-backed semantic understanding adapter for the agentic graph."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import AIProviderParsingError
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from .merging import normalize_clarification_context


_ANALYSIS_KEYS = {
    "description_language",
    "description_sufficient",
    "detected_store_domains",
    "business_summary",
    "target_audience",
    "product_direction",
    "blocking_missing_information",
    "ambiguities",
}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_SUMMARY_LENGTH = 500
_MAX_SHORT_TEXT_LENGTH = 300
_OPTIONAL_BLOCKING_KEYS = {
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
_ARABIC_BLOCKS = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


class AIUnderstandingValidationError(ValueError):
    """Raised when semantic analysis input or output is unsafe."""


def analyze_store_description(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    normalized_description: Any,
    clarification_history: Any = None,
    clarification_facts: Any = None,
    clarification_round_count: Any = 0,
) -> dict[str, Any]:
    normalized_store_id = _validate_positive_int(store_id)
    normalized_tenant_id = _validate_positive_int(tenant_id)
    _validate_positive_int(user_id)
    description = _validate_normalized_description(normalized_description)
    clarification_context = normalize_clarification_context(
        clarification_history=[] if clarification_history is None else clarification_history,
        clarification_facts={} if clarification_facts is None else clarification_facts,
        clarification_round_count=clarification_round_count,
    )

    provider = get_ai_provider_client()

    def provider_call() -> dict[str, Any]:
        return provider.analyze_store_description(
            tenant_id=normalized_tenant_id,
            store_id=normalized_store_id,
            normalized_description=description,
            clarification_context=deepcopy(clarification_context),
        )

    parsed_payload = _parse_provider_response_with_single_retry(provider_call)
    validated_payload = validate_semantic_analysis_payload(
        parsed_payload,
        clarification_facts=clarification_context["clarification_facts"],
    )
    return _json_defensive_copy(validated_payload)


def _parse_provider_response_with_single_retry(
    provider_call: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError:
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def validate_semantic_analysis_payload(
    payload: Any,
    *,
    clarification_facts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AIUnderstandingValidationError("Semantic analysis payload must be an object.")

    payload_copy = dict(deepcopy(payload))
    _assert_json_serializable(payload_copy)

    actual_keys = set(payload_copy)
    if actual_keys != _ANALYSIS_KEYS:
        raise AIUnderstandingValidationError(
            "Semantic analysis payload must match the exact contract."
        )

    language = payload_copy["description_language"]
    if language not in {"ar", "en", "unknown"}:
        raise AIUnderstandingValidationError("description_language is invalid.")

    sufficient = payload_copy["description_sufficient"]
    if not isinstance(sufficient, bool):
        raise AIUnderstandingValidationError("description_sufficient must be a boolean.")

    normalized: dict[str, Any] = {
        "description_language": language,
        "description_sufficient": sufficient,
        "detected_store_domains": _normalize_string_list(
            payload_copy["detected_store_domains"],
            field_name="detected_store_domains",
            max_items=3,
            allow_empty=True,
            max_text_length=_MAX_SHORT_TEXT_LENGTH,
            dedupe=True,
        ),
        "business_summary": _normalize_text(
            payload_copy["business_summary"],
            field_name="business_summary",
            allow_empty=False,
            max_length=_MAX_SUMMARY_LENGTH,
        ),
        "target_audience": _normalize_text(
            payload_copy["target_audience"],
            field_name="target_audience",
            allow_empty=True,
            max_length=_MAX_SHORT_TEXT_LENGTH,
        ),
        "product_direction": _normalize_string_list(
            payload_copy["product_direction"],
            field_name="product_direction",
            max_items=5,
            allow_empty=True,
            max_text_length=_MAX_SHORT_TEXT_LENGTH,
            dedupe=True,
        ),
        "blocking_missing_information": _normalize_identifier_list(
            payload_copy["blocking_missing_information"],
            max_items=5,
        ),
        "ambiguities": _normalize_string_list(
            payload_copy["ambiguities"],
            field_name="ambiguities",
            max_items=5,
            allow_empty=True,
            max_text_length=_MAX_SHORT_TEXT_LENGTH,
            dedupe=False,
        ),
    }

    _validate_cross_field_contract(normalized, clarification_facts=clarification_facts)
    _assert_json_serializable(normalized)
    return normalized


def _validate_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AIUnderstandingValidationError("Identity values must be positive integers.")
    return value


def _validate_normalized_description(value: Any) -> str:
    if not isinstance(value, str):
        raise AIUnderstandingValidationError("normalized_description must be a string.")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise AIUnderstandingValidationError("normalized_description is required.")
    return normalized


def _normalize_text(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise AIUnderstandingValidationError(f"{field_name} must be a string.")
    normalized = " ".join(value.strip().split())
    if not normalized and not allow_empty:
        raise AIUnderstandingValidationError(f"{field_name} must be non-empty.")
    if len(normalized) > max_length:
        raise AIUnderstandingValidationError(f"{field_name} is too long.")
    return normalized


def _normalize_string_list(
    value: Any,
    *,
    field_name: str,
    max_items: int,
    allow_empty: bool,
    max_text_length: int,
    dedupe: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise AIUnderstandingValidationError(f"{field_name} must be a list.")
    if len(value) > max_items:
        raise AIUnderstandingValidationError(f"{field_name} has too many items.")

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
            if dedupe:
                continue
            raise AIUnderstandingValidationError(f"{field_name} contains duplicates.")
        seen.add(key)
        normalized_items.append(normalized)

    if not allow_empty and not normalized_items:
        raise AIUnderstandingValidationError(f"{field_name} must be non-empty.")
    return normalized_items


def _normalize_identifier_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise AIUnderstandingValidationError("blocking_missing_information must be a list.")
    if len(value) > max_items:
        raise AIUnderstandingValidationError("blocking_missing_information has too many items.")

    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise AIUnderstandingValidationError(
                "blocking_missing_information items must be strings."
            )
        normalized = item.strip()
        if not _SNAKE_CASE_RE.fullmatch(normalized):
            raise AIUnderstandingValidationError(
                "blocking_missing_information items must be snake_case identifiers."
            )
        if normalized in seen:
            raise AIUnderstandingValidationError(
                "blocking_missing_information items must be unique."
            )
        if normalized in _OPTIONAL_BLOCKING_KEYS:
            raise AIUnderstandingValidationError(
                "blocking_missing_information cannot contain optional defaults."
            )
        seen.add(normalized)
        normalized_items.append(normalized)
    return normalized_items


def _validate_cross_field_contract(
    payload: Mapping[str, Any],
    *,
    clarification_facts: Mapping[str, str] | None = None,
) -> None:
    language = payload["description_language"]
    sufficient = payload["description_sufficient"]
    domains = payload["detected_store_domains"]
    product_direction = payload["product_direction"]
    blocking = payload["blocking_missing_information"]
    resolved_keys = set(clarification_facts or {})

    if sufficient is True:
        if language not in {"ar", "en"}:
            raise AIUnderstandingValidationError(
                "Sufficient analysis requires a supported language."
            )
        if not domains:
            raise AIUnderstandingValidationError(
                "Sufficient analysis requires at least one store domain."
            )
        if not product_direction:
            raise AIUnderstandingValidationError(
                "Sufficient analysis requires product direction."
            )
        if blocking != []:
            raise AIUnderstandingValidationError(
                "Sufficient analysis cannot include blocking missing information."
            )

    if sufficient is False:
        if not blocking:
            raise AIUnderstandingValidationError(
                "Insufficient analysis requires blocking missing information."
            )
        if resolved_keys.intersection(blocking):
            raise AIUnderstandingValidationError(
                "Insufficient analysis cannot repeat resolved clarification facts."
            )

    if language == "unknown":
        if sufficient is not False:
            raise AIUnderstandingValidationError(
                "Unknown language cannot be marked sufficient."
            )
        blocking_keys = set(blocking)
        if not blocking_keys.intersection({"description_language", "store_domain", "store_idea"}):
            raise AIUnderstandingValidationError(
                "Unknown language requires a language, domain, or idea blocking key."
            )


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def count_description_words(description: str) -> int:
    if not isinstance(description, str):
        return 0
    return len(normalize_description_tokens(description))


def normalize_description_tokens(description: str) -> list[str]:
    tokens: list[str] = []
    current_token: list[str] = []
    current_script: str | None = None

    def flush_token() -> None:
        nonlocal current_script
        if current_token:
            token = _strip_combining_marks("".join(current_token)).casefold()
            if token:
                tokens.append(token)
        current_token.clear()
        current_script = None

    for character in description:
        if _is_arabic_letter(character):
            script = "arabic"
        elif _is_latin_letter(character):
            script = "latin"
        elif _is_combining_mark(character) and current_script == "arabic":
            current_token.append(character)
            continue
        else:
            flush_token()
            continue

        if current_script and current_script != script:
            flush_token()
        current_script = script
        current_token.append(character)

    flush_token()
    return tokens


def _is_arabic_codepoint(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _ARABIC_BLOCKS)


def _is_arabic_letter(character: str) -> bool:
    return _is_arabic_codepoint(character) and unicodedata.category(character) == "Lo"


def _is_latin_letter(character: str) -> bool:
    return (
        unicodedata.category(character).startswith("L")
        and unicodedata.name(character, "").startswith("LATIN")
    )


def _is_combining_mark(character: str) -> bool:
    return unicodedata.category(character).startswith("M")


def _strip_combining_marks(token: str) -> str:
    return "".join(
        character for character in token if not _is_combining_mark(character)
    )


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


def _json_defensive_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


__all__ = [
    "AIUnderstandingValidationError",
    "analyze_store_description",
    "count_description_words",
    "is_positive_int",
    "normalize_description_tokens",
    "validate_semantic_analysis_payload",
]
