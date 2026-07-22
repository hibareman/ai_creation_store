"""Provider-backed repair adapter for the agentic AI Store Creation graph."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Literal

from ..constants import MAX_REPAIR_ATTEMPTS
from ..exceptions import AIProviderParsingError
from ..normalization import _apply_targeted_prevalidation_repairs
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client

RepairStrategy = Literal["section", "full"]
RepairSection = Literal["store", "store_settings", "theme", "categories", "products", "ai_analysis"]
ValidatedExpectedMode = Literal["draft_ready", "clarification"]

_ISSUE_KEYS = {"path", "code", "message", "repairable"}
_FULL_REPAIR_CODES = {
    "draft_payload_invalid",
    "response_mode_invalid",
    "clarification_questions_invalid",
}
_SECTION_REPAIR_CODE_TO_SECTION: dict[str, RepairSection] = {
    "store_section_invalid": "store",
    "store_settings_section_invalid": "store_settings",
    "theme_section_invalid": "theme",
    "theme_template_unavailable": "theme",
    "categories_section_invalid": "categories",
    "products_section_invalid": "products",
    "ai_analysis_invalid": "ai_analysis",
}
_PERSONALIZATION_REPAIR_CODES: set[str] = set()
_ALLOWED_REPAIR_CODES = _FULL_REPAIR_CODES | set(_SECTION_REPAIR_CODE_TO_SECTION) | _PERSONALIZATION_REPAIR_CODES
_REPAIR_INSTRUCTION = (
    "Repair only the listed validation problems. Preserve valid existing data. "
    "Treat the Blueprint, effective personalization context, and locked user "
    "decisions as immutable constraints. Never replace confirmed target market, "
    "pricing, brand personality, language, currency, visual preferences, "
    "clarification facts, or custom answers. "
    "The expected_mode value is included in this repair context and must be preserved. "
    "Do not change response mode by yourself. If expected_mode is draft_ready, "
    "clarification_needed must be false, clarification_questions must be an empty list, "
    "and full repair must return a complete draft payload. If expected_mode is "
    "clarification, clarification_needed must be true and clarification_questions must "
    "be a valid non-empty MCQ list. Do not add system-controlled fields. Return valid "
    "JSON only. Do not explain outside JSON. For section repair, return a JSON "
    "object containing only the requested top-level key."
)


class RepairInputError(ValueError):
    """Raised when repair state is unsafe before provider creation."""


class RepairOutputError(ValueError):
    """Raised when provider repair output cannot be used as a candidate."""


def repair_draft_payload(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    normalized_description: Any,
    expected_mode: Any,
    current_draft: Any,
    validation_errors: Any,
    available_theme_templates: Any,
    repair_attempt_count: Any,
    blueprint: Any = None,
    effective_personalization_context: Any = None,
    locked_user_decisions: Any = None,
    require_personalization_constraints: bool = False,
) -> dict[str, Any]:
    normalized_store_id = _validate_positive_int(store_id)
    normalized_tenant_id = _validate_positive_int(tenant_id)
    _validate_positive_int(user_id)
    description = _validate_description(normalized_description)
    mode = _validate_expected_mode(expected_mode)
    draft_copy = _validate_current_draft(current_draft)
    issue_list = _validate_validation_errors(validation_errors)
    theme_templates = _normalize_theme_template_names(available_theme_templates)
    current_attempt_count = _validate_repair_attempt_count(repair_attempt_count)
    constraints = _validate_constraints(
        blueprint,
        effective_personalization_context,
        locked_user_decisions,
        required=require_personalization_constraints,
    )
    next_attempt_count = current_attempt_count + 1
    strategy, target_section = _choose_repair_strategy(issue_list)
    selected_issues = _issues_for_repair(issue_list, strategy, target_section)
    repair_context = _build_repair_context(
        expected_mode=mode,
        validation_errors=selected_issues,
        next_attempt_count=next_attempt_count,
        constraints=constraints,
    )

    provider = get_ai_provider_client()

    if strategy == "section":
        candidate = _repair_section(
            provider_call=lambda: provider.regenerate_store_draft_section(
                tenant_id=normalized_tenant_id,
                store_id=normalized_store_id,
                target_section=target_section,
                original_store_description=description,
                current_draft=deepcopy(draft_copy),
                clarification_context=deepcopy(repair_context),
                available_theme_templates=deepcopy(theme_templates),
            ),
            current_draft=draft_copy,
            target_section=target_section,
        )
    else:
        candidate = _repair_full(
            provider_call=lambda: provider.regenerate_store_draft(
                tenant_id=normalized_tenant_id,
                store_id=normalized_store_id,
                original_store_description=description,
                current_draft=deepcopy(draft_copy),
                clarification_context=deepcopy(repair_context),
                available_theme_templates=deepcopy(theme_templates),
            )
        )

    normalized = _normalize_repaired_candidate(
        candidate,
        available_theme_templates=theme_templates,
    )
    if constraints:
        return _preserve_locked_draft_values(draft_copy, normalized, selected_issues)
    return normalized


def _validate_constraints(
    blueprint: Any,
    effective: Any,
    decisions: Any,
    *,
    required: bool,
) -> dict[str, Any]:
    if not required and blueprint is None and effective is None:
        return {}
    values = {
        "blueprint": blueprint,
        "effective_personalization_context": effective,
        "locked_user_decisions": decisions,
    }
    for key, value in values.items():
        if not isinstance(value, Mapping):
            raise RepairInputError(f"Repair {key} must be an object.")
    copied = deepcopy(values)
    _assert_json_serializable(copied)
    return copied


def _validate_positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RepairInputError("Repair identity values must be positive integers.")
    return value


def _validate_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepairInputError("Repair description must be a non-empty string.")
    return value


def _validate_expected_mode(value: Any) -> ValidatedExpectedMode:
    if value == "draft_ready":
        return "draft_ready"
    if value == "clarification":
        return "clarification"
    raise RepairInputError("Repair expected mode is invalid.")


def _validate_current_draft(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RepairInputError("Repair draft must be a mapping.")
    draft_copy = dict(deepcopy(value))
    _assert_json_serializable(draft_copy)
    return draft_copy


def _validate_validation_errors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise RepairInputError("Repair requires non-empty validation errors.")

    validated_errors: list[dict[str, Any]] = []
    for issue in value:
        if not isinstance(issue, Mapping):
            raise RepairInputError("Repair validation issues must be mappings.")
        issue_copy = dict(deepcopy(issue))
        if set(issue_copy) != _ISSUE_KEYS:
            raise RepairInputError("Repair validation issue structure is invalid.")
        if not isinstance(issue_copy["path"], str) or not issue_copy["path"].strip():
            raise RepairInputError("Repair validation issue path is invalid.")
        if not isinstance(issue_copy["code"], str) or not issue_copy["code"].strip():
            raise RepairInputError("Repair validation issue code is invalid.")
        if not isinstance(issue_copy["message"], str) or not issue_copy["message"].strip():
            raise RepairInputError("Repair validation issue message is invalid.")
        if issue_copy["repairable"] is not True:
            raise RepairInputError("Repair accepts only repairable issues.")
        if issue_copy["code"] not in _ALLOWED_REPAIR_CODES:
            raise RepairInputError("Repair validation issue code is unsupported.")
        _assert_json_serializable(issue_copy)
        validated_errors.append(issue_copy)

    return validated_errors


def _normalize_theme_template_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise RepairInputError("Repair theme templates must be a list.")

    normalized_templates: list[str] = []
    seen_templates: set[str] = set()
    for template_name in value:
        if not isinstance(template_name, str):
            raise RepairInputError("Repair theme template names must be strings.")
        normalized_name = " ".join(template_name.strip().split())
        if not normalized_name:
            raise RepairInputError("Repair theme template names must be non-empty.")
        if normalized_name not in seen_templates:
            normalized_templates.append(normalized_name)
            seen_templates.add(normalized_name)

    if not normalized_templates:
        raise RepairInputError("Repair requires at least one theme template.")
    return normalized_templates


def _validate_repair_attempt_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RepairInputError("Repair attempt count must be an integer.")
    if value < 0 or value >= MAX_REPAIR_ATTEMPTS:
        raise RepairInputError("Repair attempt count is outside the allowed range.")
    return value


def _choose_repair_strategy(
    validation_errors: list[dict[str, Any]],
) -> tuple[RepairStrategy, RepairSection | None]:
    priority = ("store", "store_settings", "theme", "categories", "products", "ai_analysis")
    sections = {
        _SECTION_REPAIR_CODE_TO_SECTION[issue["code"]]
        for issue in validation_errors
        if issue["code"] in _SECTION_REPAIR_CODE_TO_SECTION
    }
    if sections:
        return "section", next(section for section in priority if section in sections)
    return "full", None


def _issues_for_repair(validation_errors, strategy, target_section):
    if strategy == "full":
        return deepcopy(validation_errors)
    return [
        deepcopy(issue) for issue in validation_errors
        if _SECTION_REPAIR_CODE_TO_SECTION.get(issue["code"]) == target_section
    ]


def _build_repair_context(
    *,
    expected_mode: ValidatedExpectedMode,
    validation_errors: list[dict[str, Any]],
    next_attempt_count: int,
    constraints: dict[str, Any],
) -> dict[str, Any]:
    context = {
        "operation": "agentic_validation_repair",
        "expected_mode": expected_mode,
        "repair_attempt_count": next_attempt_count,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "validation_errors": deepcopy(validation_errors),
        "repair_instruction": _REPAIR_INSTRUCTION,
        **deepcopy(constraints),
    }
    _assert_json_serializable(context)
    return context


def _preserve_locked_draft_values(
    current: dict[str, Any], candidate: dict[str, Any], issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Accept provider changes only for top-level sections named by issues."""
    if any(issue["code"] in {"draft_payload_invalid", "response_mode_invalid", "clarification_questions_invalid"} for issue in issues):
        return candidate
    result = deepcopy(current)
    for issue in issues:
        path_parts = issue["path"].split(".")
        section = path_parts[0]
        if len(path_parts) == 1:
            if section in candidate:
                result[section] = deepcopy(candidate[section])
            continue
        if (
            len(path_parts) == 2
            and isinstance(result.get(section), Mapping)
            and isinstance(candidate.get(section), Mapping)
            and path_parts[1] in candidate[section]
        ):
            result[section][path_parts[1]] = deepcopy(
                candidate[section][path_parts[1]]
            )
    _assert_json_serializable(result)
    return result


def _repair_section(
    *,
    provider_call: Callable[[], dict[str, Any]],
    current_draft: dict[str, Any],
    target_section: RepairSection | None,
) -> dict[str, Any]:
    if target_section not in {"store", "store_settings", "theme", "categories", "products", "ai_analysis"}:
        raise RepairOutputError("Repair target section is invalid.")
    replacement_payload = _parse_provider_response_with_single_retry(provider_call)
    replacement = _extract_section_replacement(replacement_payload, target_section)
    candidate = deepcopy(current_draft)
    candidate[target_section] = deepcopy(replacement)
    return candidate


def _repair_full(
    *,
    provider_call: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    parsed_payload = _parse_provider_response_with_single_retry(provider_call)
    if not isinstance(parsed_payload, Mapping):
        raise RepairOutputError("Full repair response must be a mapping.")
    return dict(deepcopy(parsed_payload))


def _parse_provider_response_with_single_retry(
    provider_call: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError:
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def _extract_section_replacement(
    payload: Any,
    target_section: RepairSection,
) -> Any:
    if not isinstance(payload, Mapping):
        raise RepairOutputError("Section repair response must be a mapping.")
    if set(payload.keys()) != {target_section}:
        raise RepairOutputError("Section repair response must contain only the target section.")
    return deepcopy(payload[target_section])


def _normalize_repaired_candidate(
    candidate: Any,
    *,
    available_theme_templates: list[str],
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise RepairOutputError("Repaired candidate must be a mapping.")
    normalized_candidate = dict(deepcopy(candidate))
    normalized_candidate = _apply_targeted_prevalidation_repairs(
        normalized_candidate,
        available_theme_templates=available_theme_templates,
    )
    if not isinstance(normalized_candidate, Mapping):
        raise RepairOutputError("Repaired candidate normalization failed.")
    normalized_candidate = dict(deepcopy(normalized_candidate))
    _assert_json_serializable(normalized_candidate)
    return normalized_candidate


def _assert_json_serializable(value: Any) -> None:
    try:
        json.dumps(value)
    except Exception as exc:
        raise RepairInputError("Repair data must be JSON serializable.") from exc


__all__ = ["repair_draft_payload"]
