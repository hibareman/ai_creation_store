"""Provider-backed generation with technical validation only."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from ..exceptions import AIProviderParsingError
from ..normalization import _apply_targeted_prevalidation_repairs
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from ..validators import detect_ai_response_mode, validate_basic_draft_schema
from .personalization import CORE_PERSONALIZATION_KEYS, get_missing_core_personalization_keys

GeneratedDraftMode = Literal["draft_ready"]
logger = logging.getLogger(__name__)


class AIGenerationConstraintError(ValueError):
    """Raised only for technical generation-contract violations."""


def generate_initial_draft_payload(
    *,
    store_id: int,
    tenant_id: int,
    normalized_description: str,
    available_theme_templates: list[str],
    effective_personalization_context: Mapping[str, Any],
    blueprint: Mapping[str, Any] | None = None,
    description_language: str | None = None,
) -> tuple[dict[str, Any], GeneratedDraftMode]:
    """Generate a complete draft and validate JSON/schema only.

    Semantic compatibility between the idea, categories and products belongs to
    the AI prompt. The backend performs no regex, keyword or domain matching.
    """
    _validate_positive_int(store_id)
    _validate_positive_int(tenant_id)
    description = _validate_description(normalized_description)
    templates = _normalize_theme_template_names(available_theme_templates)
    context = _normalize_effective_context(effective_personalization_context)
    generation_context = deepcopy(dict(blueprint)) if isinstance(blueprint, Mapping) else _build_generation_context(
        description=description,
        context=context,
        templates=templates,
        description_language=description_language,
    )

    provider = get_ai_provider_client()

    def provider_call() -> dict[str, Any]:
        return provider.generate_agentic_store_draft(
            tenant_id=tenant_id,
            store_id=store_id,
            user_store_description=description,
            available_theme_templates=deepcopy(templates),
            blueprint=deepcopy(generation_context),
            effective_personalization_context=deepcopy(context),
        )

    parsed_payload = _parse_provider_response_with_single_retry(provider_call)
    payload = _apply_targeted_prevalidation_repairs(
        deepcopy(parsed_payload),
        available_theme_templates=templates,
    )
    payload = validate_basic_draft_schema(payload)
    mode = detect_ai_response_mode(payload)
    if mode != "draft_ready":
        raise AIGenerationConstraintError(
            "Generate must return a complete draft, not clarification questions."
        )
    _assert_json_serializable(payload)
    return dict(payload), "draft_ready"


def validate_personalization_constrained_draft(
    payload: Any,
    *,
    blueprint: Mapping[str, Any] | None = None,
    effective_personalization_context: Mapping[str, Any] | None = None,
) -> None:
    """Backward-compatible technical validator.

    Kept for callers/tests, but intentionally performs no semantic comparison.
    """
    if not isinstance(payload, Mapping):
        raise AIGenerationConstraintError("Generated draft must be an object.")
    if effective_personalization_context is not None:
        _normalize_effective_context(effective_personalization_context)
    if blueprint is not None and not isinstance(blueprint, Mapping):
        raise AIGenerationConstraintError("Generation context must be an object.")
    _assert_json_serializable(payload)


def _build_generation_context(
    *,
    description: str,
    context: Mapping[str, Any],
    templates: list[str],
    description_language: str | None,
) -> dict[str, Any]:
    """Build a lightweight prompt context without backend semantic decisions."""
    language = description_language if description_language in {"ar", "en"} else "unknown"
    result = {
        "normalized_description": description,
        "personalization": deepcopy(dict(context)),
        "description_language": language,
        "available_theme_templates": deepcopy(templates),
        "instructions": {
            "preserve_user_answers": True,
            "do_not_invent_missing_facts": True,
            "keep_categories_and_products_semantically_aligned": True,
            "use_selected_language_for_store_content": True,
            "optimize_for_content_quality_not_item_count": True,
            "create_brandable_store_identity": True,
            "write_customer_value_focused_copy": True,
            "use_strategic_non_overlapping_categories": True,
            "create_distinct_purposeful_product_mix": True,
            "create_coherent_distinctive_visual_identity": True,
        },
    }
    _assert_json_serializable(result)
    return result


def _parse_provider_response_with_single_retry(provider_call) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError:
        logger.warning("AI response parsing failed; retrying once.")
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def _normalize_effective_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AIGenerationConstraintError(
            "Effective personalization context must be an object."
        )
    normalized = dict(deepcopy(value))
    if set(normalized) != set(CORE_PERSONALIZATION_KEYS):
        raise AIGenerationConstraintError(
            "Effective personalization context must contain exactly the ten fields."
        )
    for key in CORE_PERSONALIZATION_KEYS:
        item = normalized[key]
        if not isinstance(item, str) or not item.strip():
            raise AIGenerationConstraintError(
                f"Effective personalization field {key} must be a non-empty string."
            )
        normalized[key] = " ".join(item.strip().split())
    if get_missing_core_personalization_keys(normalized):
        raise AIGenerationConstraintError(
            "Generation requires all ten personalization fields."
        )
    _assert_json_serializable(normalized)
    return normalized


def _validate_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Generation identity values must be positive integers.")
    return value


def _validate_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Generation description must be a non-empty string.")
    return " ".join(value.strip().split())


def _normalize_theme_template_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Theme templates must be provided as a list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Theme template names must be strings.")
        name = " ".join(item.strip().split())
        if not name:
            raise ValueError("Theme template names must be non-empty.")
        if name not in seen:
            seen.add(name)
            normalized.append(name)
    if not normalized:
        raise ValueError("At least one theme template is required.")
    return normalized


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value, ensure_ascii=False, allow_nan=False)


__all__ = [
    "AIGenerationConstraintError",
    "GeneratedDraftMode",
    "generate_initial_draft_payload",
    "validate_personalization_constrained_draft",
]