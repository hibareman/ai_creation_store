"""Deterministic draft validation adapter for the agentic graph."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from ..exceptions import AIDraftSchemaValidationError
from ..normalization import _ensure_theme_template_is_available
from ..validators import (
    detect_ai_response_mode,
    validate_basic_draft_schema,
    validate_categories_section,
    validate_products_section,
    validate_store_section,
    validate_store_settings_section,
    validate_theme_section,
)
from .state import ValidationIssue
from .blueprinting import AIBlueprintValidationError, validate_store_blueprint

ValidatedDraftMode = Literal["draft_ready", "clarification"]

_ISSUE_KEYS = {"path", "code", "message", "repairable"}


def validate_generated_draft(
    *,
    draft_payload: Any,
    expected_mode: Any,
    available_theme_templates: Any,
    blueprint: Any = None,
    effective_personalization_context: Any = None,
    require_personalization_context: bool = False,
) -> tuple[dict[str, Any], ValidatedDraftMode | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []

    if not isinstance(draft_payload, Mapping):
        return {}, None, [
            _issue(
                "draft_payload",
                "draft_payload_invalid",
                "Draft payload must be an object.",
                False,
            )
        ]

    try:
        payload = dict(deepcopy(draft_payload))
    except Exception:
        return {}, None, [_internal_failure_issue()]

    try:
        _assert_json_serializable(payload)
    except Exception:
        return {}, None, [_not_serializable_issue()]

    try:
        payload = validate_basic_draft_schema(payload)
    except AIDraftSchemaValidationError as exc:
        return payload, None, [
            _issue("draft_payload", "draft_payload_invalid", str(exc), True)
        ]
    except Exception:
        return payload, None, [_internal_failure_issue()]

    detected_mode: ValidatedDraftMode | None = None
    try:
        detected_mode = detect_ai_response_mode(payload)
    except AIDraftSchemaValidationError as exc:
        code = (
            "clarification_questions_invalid"
            if _looks_like_invalid_clarification_questions(payload)
            else "response_mode_invalid"
        )
        issues.append(
            _issue(
                "clarification_questions",
                code,
                str(exc),
                True,
            )
        )
    except Exception:
        issues.append(_internal_failure_issue())

    if expected_mode not in {"draft_ready", "clarification"} or (
        detected_mode is not None and expected_mode != detected_mode
    ):
        issues.append(
            _issue(
                "draft_payload",
                "state_mode_mismatch",
                "Graph mode must match the detected draft response mode.",
                False,
            )
        )

    if detected_mode == "clarification":
        return payload, detected_mode, _dedupe_issue_keys(issues)

    if detected_mode != "draft_ready":
        return payload, detected_mode, _dedupe_issue_keys(issues)

    validated_categories: list[dict[str, Any]] | None = None
    raw_category_names = _extract_raw_category_names(payload.get("categories"))

    try:
        validate_store_section(payload.get("store"))
    except AIDraftSchemaValidationError as exc:
        issues.append(_section_issue("store", "store_section_invalid", str(exc)))
    except Exception:
        issues.append(_internal_failure_issue())

    settings_valid = False
    try:
        validate_store_settings_section(payload.get("store_settings"))
        settings_valid = True
    except AIDraftSchemaValidationError as exc:
        issues.append(
            _section_issue("store_settings", "store_settings_section_invalid", str(exc))
        )
    except Exception:
        issues.append(_internal_failure_issue())

    theme_valid = False
    try:
        validate_theme_section(payload.get("theme"))
        theme_valid = True
    except AIDraftSchemaValidationError as exc:
        issues.append(_section_issue("theme", "theme_section_invalid", str(exc)))
    except Exception:
        issues.append(_internal_failure_issue())

    theme_templates = _normalize_theme_template_names(available_theme_templates)
    if theme_templates is None:
        issues.append(
            _issue(
                "available_theme_templates",
                "theme_templates_context_invalid",
                "Available theme templates must be a non-empty list of names.",
                False,
            )
        )
    elif theme_valid:
        try:
            theme_data = payload.get("theme")
            if not isinstance(theme_data, dict):
                raise AIDraftSchemaValidationError(
                    "Theme section must be a mapping object."
                )
            _ensure_theme_template_is_available(theme_data, theme_templates)
        except AIDraftSchemaValidationError as exc:
            issues.append(
                _issue(
                    "theme.theme_template",
                    "theme_template_unavailable",
                    str(exc),
                    True,
                )
            )
        except Exception:
            issues.append(_internal_failure_issue())

    try:
        validated_categories = validate_categories_section(payload.get("categories"))
    except AIDraftSchemaValidationError as exc:
        issues.append(
            _section_issue("categories", "categories_section_invalid", str(exc))
        )
    except Exception:
        issues.append(_internal_failure_issue())

    category_names = (
        [category["name"] for category in validated_categories]
        if validated_categories is not None
        else raw_category_names
    )
    if not category_names:
        issues.append(
            _issue(
                "products",
                "products_section_invalid",
                "Product/category consistency could not be validated.",
                True,
            )
        )
    else:
        try:
            validate_products_section(payload.get("products"), category_names)
        except AIDraftSchemaValidationError as exc:
            issues.append(
                _section_issue("products", "products_section_invalid", str(exc))
            )
        except Exception:
            issues.append(_internal_failure_issue())

    normalized_blueprint = _validate_personalization_context(
        blueprint=blueprint,
        effective_personalization_context=effective_personalization_context,
        available_theme_templates=available_theme_templates,
        issues=issues,
        required=require_personalization_context,
    )

    return payload, detected_mode, _dedupe_issue_keys(issues)


def _validate_personalization_context(
    *, blueprint: Any, effective_personalization_context: Any,
    available_theme_templates: Any, issues: list[ValidationIssue], required: bool,
) -> dict[str, Any] | None:
    if blueprint is None and effective_personalization_context is None:
        if required:
            issues.append(_issue(
                "blueprint", "blueprint_invalid",
                "Agentic draft validation requires personalization context.",
                False,
            ))
        return None
    try:
        return validate_store_blueprint(
            blueprint,
            effective_personalization_context=effective_personalization_context,
            available_theme_templates=available_theme_templates,
        )
    except AIBlueprintValidationError:
        issues.append(_issue(
            "blueprint", "blueprint_invalid",
            "Store Blueprint is missing required sections or conflicts with locked facts.",
            False,
        ))
    except Exception:
        issues.append(_internal_failure_issue())
    return None


def _normalize_theme_template_names(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        name = " ".join(item.strip().split())
        if not name:
            return None
        if name not in seen:
            normalized.append(name)
            seen.add(name)
    return normalized or None


def _extract_raw_category_names(categories: Any) -> list[str]:
    if not isinstance(categories, list):
        return []
    names: list[str] = []
    for category in categories:
        if isinstance(category, Mapping):
            name = category.get("name")
            if isinstance(name, str) and name.strip():
                names.append(" ".join(name.strip().split()))
    return names


def _looks_like_invalid_clarification_questions(payload: Mapping[str, Any]) -> bool:
    questions = payload.get("clarification_questions")
    return (
        payload.get("clarification_needed") is True
        and isinstance(questions, list)
        and bool(questions)
    )


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value)


def _section_issue(section: str, code: str, message: str) -> ValidationIssue:
    path = section
    import re
    quoted = re.search(r"field[: ]+'([^']+)'|field '([^']+)'|field: '([^']+)'", message)
    if quoted:
        field = next((item for item in quoted.groups() if item), None)
        if field:
            path = f"{section}.{field}"
    index = re.search(r"index (\d+)", message)
    if index and section in {"categories", "products"}:
        path = f"{section}[{index.group(1)}]" + (path[len(section):] if path != section else "")
    if "theme_template" in message:
        path = "theme.theme_template"
    return _issue(path, code, message, True)


def _issue(path: str, code: str, message: str, repairable: bool) -> ValidationIssue:
    issue: ValidationIssue = {
        "path": path,
        "code": code,
        "message": message,
        "repairable": repairable,
    }
    if set(issue.keys()) != _ISSUE_KEYS:
        raise AssertionError("ValidationIssue structure changed unexpectedly.")
    json.dumps(issue)
    return issue


def _internal_failure_issue() -> ValidationIssue:
    return _issue(
        "draft_payload",
        "validation_internal_failure",
        "Draft validation could not be completed safely.",
        False,
    )


def _not_serializable_issue() -> ValidationIssue:
    return _issue(
        "draft_payload",
        "draft_payload_not_serializable",
        "Draft payload must contain only JSON-serializable values.",
        False,
    )


def _dedupe_issue_keys(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [dict(issue) for issue in issues]


__all__ = ["ValidatedDraftMode", "validate_generated_draft"]
