"""Provider-backed generation adapter for the agentic graph foundation."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Literal

from ..exceptions import AIProviderParsingError
from ..normalization import _apply_targeted_prevalidation_repairs
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client
from ..validators import detect_ai_response_mode, validate_basic_draft_schema

GeneratedDraftMode = Literal["draft_ready"]


def generate_initial_draft_payload(
    *,
    store_id: int,
    tenant_id: int,
    normalized_description: str,
    available_theme_templates: list[str],
) -> tuple[dict[str, Any], GeneratedDraftMode]:
    _validate_positive_int(store_id)
    _validate_positive_int(tenant_id)
    description = _validate_description(normalized_description)
    theme_templates = _normalize_theme_template_names(available_theme_templates)

    provider = get_ai_provider_client()

    def provider_call() -> dict[str, Any]:
        return provider.generate_agentic_store_draft(
            tenant_id=tenant_id,
            store_id=store_id,
            user_store_description=description,
            available_theme_templates=theme_templates,
        )

    parsed_payload = _parse_provider_response_with_single_retry(provider_call)
    payload = deepcopy(parsed_payload)
    payload = _apply_targeted_prevalidation_repairs(
        payload,
        available_theme_templates=theme_templates,
    )
    payload = validate_basic_draft_schema(payload)
    mode = detect_ai_response_mode(payload)
    if mode != "draft_ready":
        raise ValueError("Agentic Generate cannot return clarification mode.")
    _assert_json_serializable(payload)
    return dict(payload), "draft_ready"


def _parse_provider_response_with_single_retry(provider_call) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError:
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def _validate_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Generation identity values must be positive integers.")
    return value


def _validate_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Generation description must be a non-empty string.")
    return value


def _normalize_theme_template_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Theme templates must be provided as a list.")

    normalized_templates: list[str] = []
    seen_templates: set[str] = set()
    for template_name in value:
        if not isinstance(template_name, str):
            raise ValueError("Theme template names must be strings.")
        normalized_name = " ".join(template_name.strip().split())
        if not normalized_name:
            raise ValueError("Theme template names must be non-empty strings.")
        if normalized_name not in seen_templates:
            normalized_templates.append(normalized_name)
            seen_templates.add(normalized_name)

    if not normalized_templates:
        raise ValueError("At least one theme template is required.")
    return normalized_templates


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value)


__all__ = ["GeneratedDraftMode", "generate_initial_draft_payload"]
