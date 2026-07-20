"""Deterministic personalization catalog for agentic store creation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ..constants import (
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
    PERSONALIZATION_INCOMPLETE_ERROR_CODE,
    PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
)

CORE_PERSONALIZATION_KEYS: tuple[str, ...] = (
    "product_offering",
    "catalog_scope",
    "target_audience",
    "target_market",
    "customer_problem",
    "unique_value_proposition",
    "price_positioning",
    "brand_personality",
    "visual_preferences",
    "language_currency",
)


PERSONALIZATION_KEY_PURPOSES = {
    "product_offering": "The core product or service being sold.",
    "catalog_scope": "The breadth and boundaries of the catalog.",
    "target_audience": "Who the store is intended to serve.",
    "target_market": "The geographic or market context for the store.",
    "customer_problem": "The customer need being solved.",
    "unique_value_proposition": "What differentiates the offer from alternatives.",
    "price_positioning": "The intended price tier and buying expectation.",
    "brand_personality": "The tone and visual identity of the brand.",
    "visual_preferences": "The preferred aesthetic references and style cues.",
    "language_currency": "The communication language and currency expectations.",
}

PERSONALIZATION_KEY_DESCRIPTIONS = {
    "product_offering": "Describe the primary products or services.",
    "catalog_scope": "Clarify whether the store is narrow or broad in scope.",
    "target_audience": "Specify the primary audience for the store.",
    "target_market": "Indicate the target market or locale.",
    "customer_problem": "Describe the problem the customer is trying to solve.",
    "unique_value_proposition": "Capture the value proposition that distinguishes the brand.",
    "price_positioning": "Clarify the expected price positioning.",
    "brand_personality": "Describe the personality the brand should convey.",
    "visual_preferences": "Describe the preferred visual direction.",
    "language_currency": "Identify the preferred language and currency.",
}

PERSONALIZATION_KEY_REQUIRED_BEFORE_BLUEPRINT = {
    key: True for key in CORE_PERSONALIZATION_KEYS
}

_OPTIONAL_ADAPTIVE_QUESTION_KEYS = {
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
_META_BLOCKING_KEYS = {
    "core_personalization_missing",
    "core_personalization_ambiguous",
}
_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_personalization_key(key: str) -> bool:
    """Return True when the provided key is a canonical personalization key."""
    return isinstance(key, str) and key in CORE_PERSONALIZATION_KEYS


def is_valid_personalization_key(key: str) -> bool:
    """Backward-compatible alias for validate_personalization_key."""
    return validate_personalization_key(key)


def get_canonical_keys() -> tuple[str, ...]:
    return CORE_PERSONALIZATION_KEYS


def key_meta(key: str) -> dict[str, Any]:
    if not validate_personalization_key(key):
        raise KeyError("Unknown personalization key")
    return {
        "purpose": PERSONALIZATION_KEY_PURPOSES[key],
        "description": PERSONALIZATION_KEY_DESCRIPTIONS[key],
        "required": PERSONALIZATION_KEY_REQUIRED_BEFORE_BLUEPRINT[key],
    }


def _is_resolved_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def ensure_json_serializable(value: Any) -> Any:
    """Return a defensive JSON copy without coercing invalid objects to text."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _normalize_personalization_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _capture_explicit(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return ""
    return _normalize_personalization_text(match.group(1)).strip(" ,.;:-")


def extract_description_personalization_facts(description: str) -> dict[str, Any]:
    """Deprecated compatibility hook.

    Semantic extraction belongs to the AI Understand node.  The backend must not
    infer business meaning from regexes or keyword dictionaries.
    """
    if not isinstance(description, str):
        raise ValueError("description must be a string.")
    return {}


def build_personalization_understanding(
    description: str,
    *,
    ai_personalization_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
    semantic_blocking_missing_information: list[str] | None = None,
) -> dict[str, Any]:
    """Build deterministic state from AI-extracted facts and user answers.

    AI facts are accepted only for the ten canonical keys.  Clarification facts
    are merged last, so the newest explicit user answers always win.
    """
    if not isinstance(description, str):
        raise ValueError("description must be a string.")
    description_facts = _validated_string_facts(
        ai_personalization_facts,
        field_name="ai_personalization_facts",
        canonical_only=True,
        allow_empty=True,
    )
    clarification_context = _validated_string_facts(
        clarification_facts,
        field_name="clarification_facts",
        canonical_only=False,
    )
    effective_context = merge_personalization_facts(description_facts, clarification_context)
    missing_keys = get_missing_core_personalization_keys(effective_context)
    semantic_blocking = _normalize_key_list(
        semantic_blocking_missing_information,
        field_name="semantic_blocking_missing_information",
    )
    ambiguous_keys = [
        key for key in CORE_PERSONALIZATION_KEYS
        if key in effective_context and key in semantic_blocking
    ]
    additional_blocking = [
        key for key in semantic_blocking
        if key not in CORE_PERSONALIZATION_KEYS and key not in _OPTIONAL_ADAPTIVE_QUESTION_KEYS
    ]
    personalization_core_complete = not missing_keys and not ambiguous_keys
    return {
        "description_personalization_facts": ensure_json_serializable(description_facts),
        "clarification_facts": ensure_json_serializable(clarification_context),
        "effective_personalization_context": ensure_json_serializable(effective_context),
        "missing_core_personalization_keys": missing_keys,
        "ambiguous_personalization_keys": ambiguous_keys,
        "personalization_core_complete": bool(personalization_core_complete),
        "additional_blocking_missing_information": additional_blocking,
        "personalization_progress": personalization_progress(description_facts, clarification_context),
    }


def _validated_string_facts(
    value: Any,
    *,
    field_name: str,
    canonical_only: bool,
    allow_empty: bool = False,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object.")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise ValueError(f"{field_name} keys must be strings.")
        key = raw_key.strip()
        if not _SNAKE_CASE_RE.fullmatch(key):
            raise ValueError(f"{field_name} keys must be snake_case.")
        if canonical_only and key not in CORE_PERSONALIZATION_KEYS:
            raise ValueError(f"{field_name} contains an unknown Core key.")
        if not isinstance(raw_value, str):
            raise ValueError(f"{field_name} values must be strings.")
        fact = _normalize_personalization_text(raw_value)
        if not fact:
            if allow_empty:
                continue
            raise ValueError(f"{field_name} values must be non-empty.")
        normalized[key] = fact
    return normalized



def _normalize_key_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} items must be strings.")
        key = item.strip()
        if not _SNAKE_CASE_RE.fullmatch(key):
            raise ValueError(f"{field_name} items must be snake_case.")
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def clarification_history_question_keys(history: Any) -> tuple[str, ...]:
    """Return previously asked question keys in first-seen order."""
    if history is None:
        return ()
    if not isinstance(history, list):
        raise ValueError("clarification_history must be a list.")
    ordered: list[str] = []
    seen: set[str] = set()
    for round_item in history:
        if not isinstance(round_item, Mapping):
            raise ValueError("clarification_history rounds must be objects.")
        questions = round_item.get("questions", [])
        if not isinstance(questions, list):
            raise ValueError("clarification_history questions must be a list.")
        for question in questions:
            if not isinstance(question, Mapping):
                raise ValueError("clarification history questions must be objects.")
            key = question.get("question_key")
            if not isinstance(key, str) or not _SNAKE_CASE_RE.fullmatch(key.strip()):
                raise ValueError("clarification history question keys must be snake_case.")
            normalized = key.strip()
            if normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
    return tuple(ordered)


def build_clarification_question_specs(question_keys: list[str] | tuple[str, ...]) -> list[dict[str, str]]:
    """Build provider-facing purposes for backend-selected question keys."""
    if not isinstance(question_keys, (list, tuple)) or not question_keys:
        raise ValueError("question_keys must be a non-empty list or tuple.")
    specs: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_key in question_keys:
        if not isinstance(raw_key, str):
            raise ValueError("question_keys must contain strings.")
        key = raw_key.strip()
        if not _SNAKE_CASE_RE.fullmatch(key) or key in seen:
            raise ValueError("question_keys must contain unique snake_case values.")
        seen.add(key)
        if key in CORE_PERSONALIZATION_KEYS:
            purpose = PERSONALIZATION_KEY_PURPOSES[key]
            question_type = "core"
        else:
            purpose = f"Resolve the blocking store decision represented by {key}."
            question_type = "adaptive"
        specs.append(
            {
                "question_key": key,
                "purpose": purpose,
                "question_type": question_type,
            }
        )
    return ensure_json_serializable(specs)


def select_clarification_question_keys(
    *,
    description_personalization_facts: dict[str, Any] | None,
    clarification_facts: dict[str, Any] | None,
    missing_core_personalization_keys: list[str] | None,
    ambiguous_personalization_keys: list[str] | None,
    additional_blocking_missing_information: list[str] | None,
    clarification_round_count: int,
    clarification_history: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Select the exact keys the provider must ask in this round.

    Rounds 1 and 2 are reserved for unresolved core personalization keys.
    Round 3 may contain only unresolved adaptive blocking keys after all core
    personalization facts are complete.
    """
    if (
        isinstance(clarification_round_count, bool)
        or not isinstance(clarification_round_count, int)
        or clarification_round_count < 0
        or clarification_round_count >= MAX_CLARIFICATION_ROUNDS
    ):
        raise ValueError("clarification_round_count is outside the askable range.")

    description_facts = (
        description_personalization_facts
        if isinstance(description_personalization_facts, dict)
        else {}
    )
    confirmed_facts = clarification_facts if isinstance(clarification_facts, dict) else {}
    effective = merge_personalization_facts(description_facts, confirmed_facts)
    resolved = set(get_resolved_core_personalization_keys(effective))
    asked = set(clarification_history_question_keys(clarification_history or []))

    declared_missing = set(
        key
        for key in _normalize_key_list(
            missing_core_personalization_keys,
            field_name="missing_core_personalization_keys",
        )
        if key in CORE_PERSONALIZATION_KEYS
    )
    declared_ambiguous = set(
        key
        for key in _normalize_key_list(
            ambiguous_personalization_keys,
            field_name="ambiguous_personalization_keys",
        )
        if key in CORE_PERSONALIZATION_KEYS
    )
    computed_missing = set(get_missing_core_personalization_keys(effective))
    unresolved_core = [
        key
        for key in CORE_PERSONALIZATION_KEYS
        if key not in resolved
        and key not in asked
        and key in (computed_missing | declared_missing | declared_ambiguous)
    ]

    if unresolved_core:
        if clarification_round_count >= MAX_CLARIFICATION_ROUNDS - 1:
            return []
        return unresolved_core[:MAX_CLARIFICATION_QUESTIONS_PER_ROUND]

    adaptive_candidates = _normalize_key_list(
        additional_blocking_missing_information,
        field_name="additional_blocking_missing_information",
    )
    selected_adaptive: list[str] = []
    for key in adaptive_candidates:
        if key in CORE_PERSONALIZATION_KEYS:
            continue
        if key in _OPTIONAL_ADAPTIVE_QUESTION_KEYS or key in _META_BLOCKING_KEYS:
            continue
        if key in asked or key in confirmed_facts:
            continue
        selected_adaptive.append(key)
        if len(selected_adaptive) >= MAX_CLARIFICATION_QUESTIONS_PER_ROUND:
            break
    return selected_adaptive


def has_unresolved_personalization_blockers(
    *,
    missing_core_personalization_keys: Any,
    ambiguous_personalization_keys: Any,
    additional_blocking_missing_information: Any,
) -> bool:
    return bool(
        _normalize_key_list(
            missing_core_personalization_keys,
            field_name="missing_core_personalization_keys",
        )
        or _normalize_key_list(
            ambiguous_personalization_keys,
            field_name="ambiguous_personalization_keys",
        )
        or [
            key
            for key in _normalize_key_list(
                additional_blocking_missing_information,
                field_name="additional_blocking_missing_information",
            )
            if key not in _META_BLOCKING_KEYS
        ]
    )

def get_resolved_core_personalization_keys(facts: dict[str, Any]) -> tuple[str, ...]:
    """Return the canonical keys that already have a resolved value."""
    resolved: list[str] = []
    for key in CORE_PERSONALIZATION_KEYS:
        value = facts.get(key) if isinstance(facts, dict) else None
        if _is_resolved_value(value):
            resolved.append(key)
    return tuple(resolved)


def get_missing_core_personalization_keys(facts: dict[str, Any]) -> list[str]:
    """Return the missing canonical keys in stable order."""
    resolved = set(get_resolved_core_personalization_keys(facts))
    return [key for key in CORE_PERSONALIZATION_KEYS if key not in resolved]


def select_next_personalization_keys(
    facts: dict[str, Any],
    *,
    limit: int = MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
) -> list[str]:
    """Select up to five missing keys in canonical order."""
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    selected: list[str] = []
    for key in get_missing_core_personalization_keys(facts):
        selected.append(key)
        if len(selected) >= min(limit, MAX_CLARIFICATION_QUESTIONS_PER_ROUND):
            break
    return selected


def merge_personalization_facts(
    description_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge personalization facts with clarification facts taking precedence."""
    merged: dict[str, Any] = {}

    if isinstance(description_facts, dict):
        for key in CORE_PERSONALIZATION_KEYS:
            value = description_facts.get(key)
            if _is_resolved_value(value):
                merged[key] = value

    if isinstance(clarification_facts, dict):
        for key, value in clarification_facts.items():
            if validate_personalization_key(key) and _is_resolved_value(value):
                merged[key] = value

    return ensure_json_serializable(merged)


def resolved_core_keys_from(
    description_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper returning the merged resolved facts mapping."""
    return merge_personalization_facts(description_facts, clarification_facts)


def missing_core_keys(
    description_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
) -> list[str]:
    return get_missing_core_personalization_keys(
        merge_personalization_facts(description_facts, clarification_facts)
    )


def next_missing_keys(
    description_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
    max_questions: int | None = None,
) -> list[str]:
    if max_questions is None:
        max_questions = MAX_CLARIFICATION_QUESTIONS_PER_ROUND
    return select_next_personalization_keys(
        merge_personalization_facts(description_facts, clarification_facts),
        limit=max_questions,
    )


def personalization_progress(
    description_facts: dict[str, Any] | None = None,
    clarification_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = merge_personalization_facts(description_facts, clarification_facts)
    resolved = list(get_resolved_core_personalization_keys(merged))
    missing = get_missing_core_personalization_keys(merged)
    output = {
        "resolved_core_count": len(resolved),
        "total_core_count": len(CORE_PERSONALIZATION_KEYS),
        "core_complete": len(resolved) == len(CORE_PERSONALIZATION_KEYS),
        "missing_core_keys": missing,
    }
    json.dumps(output, ensure_ascii=False)
    return output


__all__ = [
    "CORE_PERSONALIZATION_KEYS",
    "MAX_CLARIFICATION_QUESTIONS_PER_ROUND",
    "PERSONALIZATION_INCOMPLETE_ERROR_CODE",
    "PERSONALIZATION_INCOMPLETE_USER_MESSAGE",
    "PERSONALIZATION_KEY_DESCRIPTIONS",
    "PERSONALIZATION_KEY_PURPOSES",
    "PERSONALIZATION_KEY_REQUIRED_BEFORE_BLUEPRINT",
    "ensure_json_serializable",
    "get_canonical_keys",
    "get_missing_core_personalization_keys",
    "get_resolved_core_personalization_keys",
    "is_valid_personalization_key",
    "key_meta",
    "merge_personalization_facts",
    "missing_core_keys",
    "next_missing_keys",
    "personalization_progress",
    "resolved_core_keys_from",
    "select_next_personalization_keys",
    "validate_personalization_key",
    "build_personalization_understanding",
    "extract_description_personalization_facts",
    "build_clarification_question_specs",
    "clarification_history_question_keys",
    "has_unresolved_personalization_blockers",
    "select_clarification_question_keys",
]
