"""
AI provider output normalization and safe pre-validation repair helpers.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .exceptions import AIDraftSchemaValidationError


_MAX_DRAFT_PRODUCTS = 4


def _ensure_theme_template_is_available(
    theme_data: dict[str, Any],
    available_theme_templates: list[str],
) -> None:
    """
    Ensure theme_template matches an exact currently available ThemeTemplate name.
    """
    selected_template_name = theme_data.get("theme_template")
    if not isinstance(selected_template_name, str):
        raise AIDraftSchemaValidationError(
            "Theme field 'theme_template' must match an available ThemeTemplate name."
        )

    normalized_selected = " ".join(selected_template_name.strip().split())
    available_names = [
        " ".join(str(template_name).strip().split())
        for template_name in available_theme_templates
        if str(template_name).strip()
    ]

    if normalized_selected in set(available_names):
        theme_data["theme_template"] = normalized_selected
        return

    selected_folded = normalized_selected.casefold()
    folded_map: dict[str, str] = {}
    duplicate_folded_keys: set[str] = set()
    for available_name in available_names:
        folded = available_name.casefold()
        if folded in folded_map and folded_map[folded] != available_name:
            duplicate_folded_keys.add(folded)
            continue
        folded_map[folded] = available_name

    if selected_folded in folded_map and selected_folded not in duplicate_folded_keys:
        theme_data["theme_template"] = folded_map[selected_folded]
        return

    raise AIDraftSchemaValidationError(
        "Theme field 'theme_template' must match an available ThemeTemplate name."
    )


def _normalize_text_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _tokenize_hint(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^0-9A-Za-z\u0600-\u06FF]+", value.casefold())
        if token
    }


def _resolve_template_name_from_hints(
    hint_values: Sequence[Any],
    available_theme_templates: Sequence[str],
) -> str | None:
    available_names = [
        _normalize_text_value(template_name)
        for template_name in available_theme_templates
        if _normalize_text_value(template_name)
    ]
    if not available_names:
        return None

    folded_map: dict[str, str] = {}
    duplicate_folded_keys: set[str] = set()
    for available_name in available_names:
        folded = available_name.casefold()
        if folded in folded_map and folded_map[folded] != available_name:
            duplicate_folded_keys.add(folded)
            continue
        folded_map[folded] = available_name

    normalized_hints = [
        _normalize_text_value(hint_value) for hint_value in hint_values if _normalize_text_value(hint_value)
    ]
    for hint in normalized_hints:
        folded_hint = hint.casefold()
        if folded_hint in folded_map and folded_hint not in duplicate_folded_keys:
            return folded_map[folded_hint]

    for hint in normalized_hints:
        hint_tokens = _tokenize_hint(hint)
        if not hint_tokens:
            continue
        matched_templates: list[str] = []
        for available_name in available_names:
            available_tokens = _tokenize_hint(available_name)
            if available_tokens and available_tokens.issubset(hint_tokens):
                matched_templates.append(available_name)
        unique_matches = list(dict.fromkeys(matched_templates))
        if len(unique_matches) == 1:
            return unique_matches[0]

    return None


def _cleanup_clarification_question_options(payload: dict[str, Any]) -> None:
    questions = payload.get("clarification_questions")
    if not isinstance(questions, list):
        return

    for question in questions:
        if not isinstance(question, dict):
            continue
        options = question.get("options")
        if not isinstance(options, list):
            continue
        cleaned_options = []
        for option in options:
            normalized_option = _normalize_text_value(option)
            if normalized_option:
                cleaned_options.append(normalized_option)
        question["options"] = cleaned_options


def _trim_products_overflow(payload: dict[str, Any]) -> None:
    products = payload.get("products")
    if isinstance(products, list) and len(products) > _MAX_DRAFT_PRODUCTS:
        payload["products"] = products[:_MAX_DRAFT_PRODUCTS]


def _normalize_products_image_url(payload: dict[str, Any]) -> None:
    products = payload.get("products")
    if not isinstance(products, list):
        return

    for product in products:
        if not isinstance(product, dict):
            continue
        if "image_url" not in product or product.get("image_url") is None:
            product["image_url"] = ""


def _resolve_theme_template_from_payload_hints(
    payload: dict[str, Any],
    available_theme_templates: Sequence[str],
) -> None:
    if not available_theme_templates:
        return

    theme_data = payload.get("theme")
    if not isinstance(theme_data, dict):
        return

    explicit_template = _normalize_text_value(theme_data.get("theme_template"))
    if explicit_template:
        resolved_from_explicit = _resolve_template_name_from_hints(
            [explicit_template],
            available_theme_templates,
        )
        if resolved_from_explicit:
            theme_data["theme_template"] = resolved_from_explicit
        return

    hint_values: list[Any] = []
    for key in (
        "style",
        "theme_style",
        "themeStyle",
        "template",
        "template_name",
        "templateName",
        "theme_name",
        "themeName",
    ):
        hint_values.append(theme_data.get(key))
        hint_values.append(payload.get(key))

    store_data = payload.get("store")
    if isinstance(store_data, Mapping):
        hint_values.append(store_data.get("style"))

    resolved = _resolve_template_name_from_hints(hint_values, available_theme_templates)
    if resolved:
        theme_data["theme_template"] = resolved


def _apply_targeted_prevalidation_repairs(
    payload: dict[str, Any],
    *,
    available_theme_templates: Sequence[str] | None = None,
) -> dict[str, Any]:
    _trim_products_overflow(payload)
    _normalize_products_image_url(payload)
    _cleanup_clarification_question_options(payload)
    if available_theme_templates is not None:
        _resolve_theme_template_from_payload_hints(payload, available_theme_templates)
    return payload


__all__ = [
    "_apply_targeted_prevalidation_repairs",
    "_ensure_theme_template_is_available",
]
