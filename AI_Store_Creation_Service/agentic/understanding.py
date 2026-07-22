"""Provider-backed semantic understanding adapter for the agentic graph."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import AIProviderParsingError
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from .merging import normalize_clarification_context
from .personalization import CORE_PERSONALIZATION_KEYS


logger = logging.getLogger(__name__)
_MAX_LOGGED_PROVIDER_RESPONSE_CHARS = 20000


def _safe_log_value(value: Any) -> str:
    """Return a bounded, serialization-safe representation for diagnostics."""
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        rendered = repr(value)
    if len(rendered) > _MAX_LOGGED_PROVIDER_RESPONSE_CHARS:
        return rendered[:_MAX_LOGGED_PROVIDER_RESPONSE_CHARS] + "...<truncated>"
    return rendered


_ANALYSIS_KEYS = {
    "description_language",
    "description_sufficient",
    "detected_store_domains",
    "target_audience",
    "product_direction",
    "personalization",
    "blocking_missing_information",
    "missing_information",
    "confidence_score",
    "ambiguities",
    "store_understanding",
}
_LEGACY_ANALYSIS_KEYS = _ANALYSIS_KEYS - {"missing_information", "confidence_score"}
_PROVIDER_WRAPPER_KEYS = ("analysis", "semantic_analysis", "result", "data", "output")
_IGNORED_PROVIDER_KEYS = {
    "completion_percentage",
    "understood_summary",
    "clarification_needed",
    "clarification_questions",
}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_SHORT_TEXT_LENGTH = 300
_MAX_MISSING_INFORMATION_ITEMS = len(CORE_PERSONALIZATION_KEYS)
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
    try:
        validated_payload = validate_semantic_analysis_payload(
            parsed_payload,
            clarification_facts=clarification_context["clarification_facts"],
        )
    except Exception as validation_error:
        logger.exception(
            "AI semantic payload validation failed | store_id=%s | "
            "tenant_id=%s | error=%s | parsed_payload=%s",
            normalized_store_id,
            normalized_tenant_id,
            validation_error,
            _safe_log_value(parsed_payload),
        )
        raise
    return _json_defensive_copy(validated_payload)


def _parse_provider_response_with_single_retry(
    provider_call: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError as first_error:
        logger.exception(
            "AI provider response parsing failed on first attempt | "
            "error=%s | raw_response=%s",
            first_error,
            _safe_log_value(raw_response),
        )

    raw_response_retry = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response_retry)
    except AIProviderParsingError as retry_error:
        logger.exception(
            "AI provider response parsing failed after retry | "
            "error=%s | raw_response=%s",
            retry_error,
            _safe_log_value(raw_response_retry),
        )
        raise


def validate_semantic_analysis_payload(
    payload: Any,
    *,
    clarification_facts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Project provider JSON into the canonical Understand state shape.

    The provider boundary validates JSON syntax/object shape only.  It does not
    reject otherwise parseable AI output for missing fields, extra fields,
    imperfect types, or cross-field business consistency.  Known fields are
    copied when structurally usable and safe defaults are supplied otherwise.
    No business meaning is inferred by the backend.
    """
    del clarification_facts  # Kept for public-signature compatibility.

    if not isinstance(payload, Mapping):
        raise AIUnderstandingValidationError(
            "Semantic analysis payload must be a JSON object."
        )

    payload_copy = _unwrap_semantic_analysis_payload(dict(deepcopy(payload)))
    _assert_json_serializable(payload_copy)

    personalization = _project_personalization_object(
        payload_copy.get("personalization")
    )

    # Some models return canonical facts at the top level.  Accept those values
    # only when the nested canonical field is absent; this is structural
    # compatibility, not semantic interpretation.
    for key in CORE_PERSONALIZATION_KEYS:
        if not personalization[key]:
            raw_value = payload_copy.get(key)
            if isinstance(raw_value, str):
                personalization[key] = raw_value

    target_audience = _project_string(payload_copy.get("target_audience"))
    if not target_audience:
        target_audience = personalization.get("target_audience", "")

    normalized: dict[str, Any] = {
        "description_language": _project_language(
            payload_copy.get("description_language")
        ),
        "description_sufficient": _project_boolean(
            payload_copy.get("description_sufficient"), default=False
        ),
        "detected_store_domains": _project_string_list(
            payload_copy.get("detected_store_domains")
        ),
        "target_audience": target_audience,
        "product_direction": _project_string_list(
            payload_copy.get("product_direction")
        ),
        "personalization": personalization,
        "blocking_missing_information": _project_string_list(
            payload_copy.get("blocking_missing_information")
        ),
        "missing_information": _project_string_list(
            payload_copy.get("missing_information")
        ),
        "confidence_score": _project_confidence_score(
            payload_copy.get("confidence_score")
        ),
        "ambiguities": _project_string_list(payload_copy.get("ambiguities")),
        "ai_consultant_message": _project_text(payload_copy.get("store_understanding")),
    }

    _assert_json_serializable(normalized)
    return normalized


def _project_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _project_string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _project_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [value]
    return []


def _project_boolean(value: Any, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _project_language(value: Any) -> str:
    if isinstance(value, str) and value in {"ar", "en", "unknown"}:
        return value
    return "unknown"


def _project_confidence_score(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if not numeric.is_finite():
        return 0
    if Decimal("0") <= numeric <= Decimal("1") and not isinstance(value, int):
        numeric *= Decimal("100")
    numeric = min(Decimal("100"), max(Decimal("0"), numeric))
    return int(numeric.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _project_personalization_object(value: Any) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    return {
        key: raw if isinstance((raw := source.get(key)), str) else ""
        for key in CORE_PERSONALIZATION_KEYS
    }


def _friendly_missing_information(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = {
        "product_offering": "what products or services the store should sell",
        "catalog_scope": "how broad or focused the product catalog should be",
        "target_audience": "who the store is intended to serve",
        "target_market": "which market or region the store should target",
        "customer_problem": "what customer need or problem the store addresses",
        "unique_value_proposition": "what makes the store meaningfully different",
        "price_positioning": "the intended pricing level or positioning",
        "brand_personality": "the desired brand personality or tone",
        "visual_preferences": "the preferred visual style or design direction",
        "language_currency": "the preferred store language and currency",
    }
    return [
        labels[item]
        for item in value
        if isinstance(item, str) and item in labels
    ]


def _unwrap_semantic_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap one common provider envelope without interpreting content."""
    if set(payload) & _ANALYSIS_KEYS:
        return payload

    matching_wrappers = [
        key for key in _PROVIDER_WRAPPER_KEYS if isinstance(payload.get(key), Mapping)
    ]
    if len(matching_wrappers) == 1:
        return dict(deepcopy(payload[matching_wrappers[0]]))
    return payload


def _normalize_confidence_score(value: Any) -> int:
    if isinstance(value, bool):
        raise AIUnderstandingValidationError("confidence_score must be numeric.")

    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AIUnderstandingValidationError("confidence_score must be numeric.")

    if not numeric.is_finite():
        raise AIUnderstandingValidationError("confidence_score must be finite.")

    # Accept both probability-style scores (0..1) and percentage-style scores
    # (0..100), then store the canonical backend representation as an integer.
    if Decimal("0") <= numeric <= Decimal("1") and not isinstance(value, int):
        numeric *= Decimal("100")

    if numeric < 0 or numeric > 100:
        raise AIUnderstandingValidationError(
            "confidence_score must be between 0 and 100."
        )

    return int(numeric.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_personalization_object(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise AIUnderstandingValidationError("personalization must be an object.")
    unknown_keys = set(value) - set(CORE_PERSONALIZATION_KEYS)
    if unknown_keys:
        raise AIUnderstandingValidationError(
            "personalization contains unsupported keys: "
            + ", ".join(sorted(unknown_keys))
        )
    normalized: dict[str, str] = {}
    for key in CORE_PERSONALIZATION_KEYS:
        raw = value.get(key, "")
        if not isinstance(raw, str):
            raise AIUnderstandingValidationError(
                f"personalization.{key} must be a string."
            )
        text = " ".join(raw.strip().split())
        if len(text) > _MAX_SHORT_TEXT_LENGTH:
            raise AIUnderstandingValidationError(
                f"personalization.{key} is too long."
            )
        normalized[key] = text
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
    blocking = payload["blocking_missing_information"]
    missing_information = payload["missing_information"]
    personalization = payload["personalization"]
    resolved_keys = set(clarification_facts or {})
    missing = [key for key in CORE_PERSONALIZATION_KEYS if not personalization[key]]

    if missing_information and blocking and [
        item.casefold() for item in missing_information
    ] == [item.casefold() for item in blocking]:
        raise AIUnderstandingValidationError(
            "missing_information must not duplicate blocking_missing_information."
        )
    if any(item in blocking for item in missing_information):
        raise AIUnderstandingValidationError(
            "missing_information must contain user-friendly descriptions."
        )

    if language not in {"ar", "en", "unknown"}:
        raise AIUnderstandingValidationError("Unsupported description language.")
    if sufficient is True:
        if language not in {"ar", "en"}:
            raise AIUnderstandingValidationError(
                "Sufficient analysis requires a supported language."
            )
        if missing:
            raise AIUnderstandingValidationError(
                "Sufficient analysis requires all ten personalization fields."
            )
        if blocking:
            raise AIUnderstandingValidationError(
                "Sufficient analysis cannot include blocking missing information."
            )
        if missing_information:
            raise AIUnderstandingValidationError(
                "Sufficient analysis cannot include missing information descriptions."
            )
    else:
        expected_missing = [key for key in missing if key not in resolved_keys]
        if not expected_missing and not blocking:
            raise AIUnderstandingValidationError(
                "Insufficient analysis requires unresolved missing information."
            )
        if resolved_keys.intersection(blocking):
            raise AIUnderstandingValidationError(
                "Insufficient analysis cannot repeat resolved clarification facts."
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
