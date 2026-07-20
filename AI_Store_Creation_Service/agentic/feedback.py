"""Deterministic Feedback contract and builder.

Feedback is derived exclusively from the current Understand state. It performs
no AI calls, semantic extraction, regex matching, or business inference.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TypedDict

from .personalization import CORE_PERSONALIZATION_KEYS


class FeedbackContract(TypedDict):
    understood_summary: str
    completion_percentage: int
    missing_information: list[str]
    description_sufficient: bool
    confidence_score: int


_AR_LABELS = {
    "product_offering": "المنتجات أو الخدمات",
    "catalog_scope": "نطاق الكتالوج",
    "target_audience": "الجمهور المستهدف",
    "target_market": "السوق المستهدف",
    "customer_problem": "حاجة العميل",
    "unique_value_proposition": "القيمة المميزة",
    "price_positioning": "الفئة السعرية",
    "brand_personality": "شخصية العلامة",
    "visual_preferences": "التفضيلات البصرية",
    "language_currency": "اللغة والعملة",
}
_EN_LABELS = {
    "product_offering": "Products or services",
    "catalog_scope": "Catalog scope",
    "target_audience": "Target audience",
    "target_market": "Target market",
    "customer_problem": "Customer need",
    "unique_value_proposition": "Unique value",
    "price_positioning": "Price positioning",
    "brand_personality": "Brand personality",
    "visual_preferences": "Visual direction",
    "language_currency": "Language and currency",
}
def _resolve_output_language(state: Mapping[str, Any]) -> str:
    context = state.get("effective_personalization_context")

    if isinstance(context, Mapping):
        value = context.get("language_currency")

        if isinstance(value, str):
            normalized = value.lower()

            if "english" in normalized or "الإنجليزية" in normalized or "الانكليزية" in normalized:
                return "en"

            if "arabic" in normalized or "العربية" in normalized:
                return "ar"

    description_language = state.get("description_language")
    return description_language if description_language in {"ar", "en"} else "en"


def build_feedback(state: Mapping[str, Any]) -> FeedbackContract:
    """Transform valid Understand output into a user-facing Feedback object."""
    if not isinstance(state, Mapping):
        raise ValueError("Feedback state must be an object.")

    understanding_valid = state.get("understanding_valid") is True
    context = _confirmed_context(state.get("effective_personalization_context"))
    missing_information = _string_list_exact_copy(state.get("missing_information", []))

    feedback: FeedbackContract = {
        "understood_summary": _build_understood_summary(
            context=context,
            language=_resolve_output_language(state),
            understanding_valid=understanding_valid,
        ),
        "completion_percentage": _completion_percentage(context),
        "missing_information": missing_information,
        "description_sufficient": bool(
            understanding_valid and state.get("description_sufficient") is True
        ),
        "confidence_score": _confidence_score(state.get("confidence_score")),
    }
    return validate_feedback_contract(feedback)


def validate_feedback_contract(value: Any) -> FeedbackContract:
    if not isinstance(value, Mapping):
        raise ValueError("Feedback payload must be an object.")
    expected = {
        "understood_summary",
        "completion_percentage",
        "missing_information",
        "description_sufficient",
        "confidence_score",
    }
    if set(value) != expected:
        raise ValueError("Feedback payload must match the exact contract.")

    summary = value["understood_summary"]
    percentage = value["completion_percentage"]
    missing = value["missing_information"]
    sufficient = value["description_sufficient"]
    confidence = value["confidence_score"]
    if not isinstance(summary, str):
        raise ValueError("understood_summary must be a string.")
    if isinstance(percentage, bool) or not isinstance(percentage, int) or not 0 <= percentage <= 100:
        raise ValueError("completion_percentage must be an integer from 0 to 100.")
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        raise ValueError("missing_information must be a list of strings.")
    if not isinstance(sufficient, bool):
        raise ValueError("description_sufficient must be a boolean.")
    if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 100:
        raise ValueError("confidence_score must be an integer from 0 to 100.")

    normalized: FeedbackContract = {
        "understood_summary": summary,
        "completion_percentage": percentage,
        "missing_information": list(missing),
        "description_sufficient": sufficient,
        "confidence_score": confidence,
    }
    json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    return normalized


def _confirmed_context(value: Any) -> dict[str, str]:
    """Return only confirmed canonical facts without rewriting their values."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in CORE_PERSONALIZATION_KEYS:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            result[key] = item
    return result


def _completion_percentage(context: Mapping[str, str]) -> int:
    """Compute deterministic progress exclusively from the ten canonical facts."""
    total = len(CORE_PERSONALIZATION_KEYS)
    resolved = sum(
        1
        for key in CORE_PERSONALIZATION_KEYS
        if isinstance(context.get(key), str) and bool(context[key].strip())
    )
    return (resolved * 100) // total


def _build_understood_summary(*, context: Mapping[str, str], language: Any, understanding_valid: bool) -> str:
    is_arabic = language == "ar"
    if not understanding_valid or not context:
        return "لم نتمكن من تأكيد معلومات المتجر بعد." if is_arabic else "No store information has been confirmed yet."

    labels = _AR_LABELS if is_arabic else _EN_LABELS
    parts = [f"{labels[key]}: {context[key]}" for key in CORE_PERSONALIZATION_KEYS if key in context]
    # Keep merchant feedback concise while using only confirmed values.
    selected = parts[:4]
    prefix = "فهمنا أن " if is_arabic else "We understood: "
    separator = "، " if is_arabic else "; "
    return prefix + separator.join(selected) + "."


def _string_list_exact_copy(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("missing_information must be a list of strings.")
    return list(value)


def _confidence_score(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return 0
    return value


__all__ = ["FeedbackContract", "build_feedback", "validate_feedback_contract"]
