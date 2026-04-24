

from __future__ import annotations

import re
from numbers import Real
from typing import Any, Literal, Mapping, Sequence


class AIDraftSchemaValidationError(ValueError):
    """Raised when parsed AI draft payload fails basic top-level schema checks."""


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_CHANNEL = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_ALPHA = r"(?:0|1|0?\.\d+)"
_HUE = r"(?:360|3[0-5]\d|[12]\d\d|[1-9]?\d)"
_PERCENT = r"(?:100|[1-9]?\d)%"

_RGB_COLOR_RE = re.compile(
    rf"^rgb\(\s*{_RGB_CHANNEL}\s*,\s*{_RGB_CHANNEL}\s*,\s*{_RGB_CHANNEL}\s*\)$",
    re.IGNORECASE,
)
_RGBA_COLOR_RE = re.compile(
    rf"^rgba\(\s*{_RGB_CHANNEL}\s*,\s*{_RGB_CHANNEL}\s*,\s*{_RGB_CHANNEL}\s*,\s*{_ALPHA}\s*\)$",
    re.IGNORECASE,
)
_HSL_COLOR_RE = re.compile(
    rf"^hsl\(\s*{_HUE}\s*,\s*{_PERCENT}\s*,\s*{_PERCENT}\s*\)$",
    re.IGNORECASE,
)
_HSLA_COLOR_RE = re.compile(
    rf"^hsla\(\s*{_HUE}\s*,\s*{_PERCENT}\s*,\s*{_PERCENT}\s*,\s*{_ALPHA}\s*\)$",
    re.IGNORECASE,
)

_DEFAULT_CLARIFICATION_QUESTIONS = [
    {
        "question_key": "store_type",
        "question_text": "What type of store do you want to create?",
        "options": ["Fashion", "Electronics", "Food & Grocery", "Other"],
    }
]


def _ensure_key_of_type(
    payload: Mapping[str, Any],
    key: str,
    expected_type: type | tuple[type, ...],
) -> None:
    if key not in payload:
        raise AIDraftSchemaValidationError(f"Missing required top-level key: '{key}'.")

    value = payload[key]
    if not isinstance(value, expected_type):
        expected_name = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " | ".join(t.__name__ for t in expected_type)
        )
        actual_name = type(value).__name__
        raise AIDraftSchemaValidationError(
            f"Invalid type for '{key}': expected {expected_name}, got {actual_name}."
        )


def validate_basic_draft_schema(payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate only the basic top-level AI draft schema.

    Behavior:
    - `clarification_needed` and `clarification_questions` are always required.
    - Structural keys (`store`, `store_settings`, `theme`, `categories`, `products`)
      are normalized to safe empty defaults when missing.

    This makes clarification-mode payloads from smaller local models robust, while
    still enforcing strict typing and mode consistency in later validators.
    """
    if not isinstance(payload, Mapping):
        raise AIDraftSchemaValidationError("Draft payload must be a mapping object.")

    normalized = dict(payload)

    # Structural keys (safe defaults when missing).
    structure_defaults: dict[str, Any] = {
        "store": {},
        "store_settings": {},
        "theme": {},
        "categories": [],
        "products": [],
    }
    for key, default_value in structure_defaults.items():
        if key not in normalized:
            normalized[key] = default_value

    _ensure_key_of_type(normalized, "store", Mapping)
    _ensure_key_of_type(normalized, "store_settings", Mapping)
    _ensure_key_of_type(normalized, "theme", Mapping)
    _ensure_key_of_type(normalized, "categories", list)
    _ensure_key_of_type(normalized, "products", list)

    # Clarification keys:
    # - tolerate missing provider fields by inferring safe defaults
    # - still enforce final types strictly.
    if "clarification_questions" not in normalized:
        normalized["clarification_questions"] = []

    _ensure_key_of_type(normalized, "clarification_questions", list)

    if "clarification_needed" not in normalized:
        has_structural_content = any(
            bool(normalized.get(key))
            for key in ("store", "store_settings", "theme", "categories", "products")
        )
        if normalized["clarification_questions"]:
            normalized["clarification_needed"] = True
        else:
            # If we already have meaningful draft content, treat it as draft-ready.
            # Otherwise default to clarification mode.
            normalized["clarification_needed"] = not has_structural_content

    _ensure_key_of_type(normalized, "clarification_needed", bool)

    # Keep clarification mode internally consistent even when provider omitted questions.
    if normalized["clarification_needed"] and not normalized["clarification_questions"]:
        normalized["clarification_questions"] = list(_DEFAULT_CLARIFICATION_QUESTIONS)

    return normalized


def validate_store_section(store_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate draft `store` section at a practical level for draft-ready payloads.
    """
    if not isinstance(store_data, Mapping):
        raise AIDraftSchemaValidationError("Store section must be a mapping object.")

    if "name" not in store_data:
        raise AIDraftSchemaValidationError("Missing required store field: 'name'.")
    name = store_data["name"]
    if not isinstance(name, str) or not name.strip():
        raise AIDraftSchemaValidationError("Store field 'name' must be a non-empty string.")

    if "description" not in store_data:
        raise AIDraftSchemaValidationError("Missing required store field: 'description'.")
    description = store_data["description"]
    if not isinstance(description, str):
        raise AIDraftSchemaValidationError("Store field 'description' must be a string.")

    return dict(store_data)


def validate_store_settings_section(store_settings_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate draft `store_settings` section for draft-ready payloads.
    """
    if not isinstance(store_settings_data, Mapping):
        raise AIDraftSchemaValidationError("store_settings section must be a mapping object.")

    for key in ("currency", "language", "timezone"):
        if key not in store_settings_data:
            raise AIDraftSchemaValidationError(
                f"Missing required store_settings field: '{key}'."
            )
        value = store_settings_data[key]
        if not isinstance(value, str) or not value.strip():
            raise AIDraftSchemaValidationError(
                f"store_settings field '{key}' must be a non-empty string."
            )

    return dict(store_settings_data)


def _require_non_empty_string(theme_data: Mapping[str, Any], key: str) -> str:
    if key not in theme_data:
        raise AIDraftSchemaValidationError(f"Missing required theme field: '{key}'.")
    value = theme_data[key]
    if not isinstance(value, str):
        raise AIDraftSchemaValidationError(f"Theme field '{key}' must be a string.")
    normalized = value.strip()
    if not normalized:
        raise AIDraftSchemaValidationError(f"Theme field '{key}' must be a non-empty string.")
    return normalized


def _is_reasonable_color_value(value: str) -> bool:
    return bool(
        _HEX_COLOR_RE.match(value)
        or _RGB_COLOR_RE.match(value)
        or _RGBA_COLOR_RE.match(value)
        or _HSL_COLOR_RE.match(value)
        or _HSLA_COLOR_RE.match(value)
    )


def validate_theme_section(theme_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate structure and basic value shape for the AI draft `theme` section only.
    """
    if not isinstance(theme_data, Mapping):
        raise AIDraftSchemaValidationError("Theme section must be a mapping object.")

    theme_template = _require_non_empty_string(theme_data, "theme_template")
    if theme_template.isdigit():
        raise AIDraftSchemaValidationError(
            "Theme field 'theme_template' must be a template name, not an ID."
        )

    primary_color = _require_non_empty_string(theme_data, "primary_color")
    if not _is_reasonable_color_value(primary_color):
        raise AIDraftSchemaValidationError(
            "Theme field 'primary_color' has an invalid color format."
        )

    secondary_color = _require_non_empty_string(theme_data, "secondary_color")
    if not _is_reasonable_color_value(secondary_color):
        raise AIDraftSchemaValidationError(
            "Theme field 'secondary_color' has an invalid color format."
        )

    _require_non_empty_string(theme_data, "font_family")

    for key in ("logo_url", "banner_url"):
        if key not in theme_data:
            raise AIDraftSchemaValidationError(f"Missing required theme field: '{key}'.")
        if not isinstance(theme_data[key], str):
            raise AIDraftSchemaValidationError(
                f"Theme field '{key}' must be a string (empty string is allowed)."
            )

    return dict(theme_data)


def _normalize_category_name(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def validate_categories_section(categories_data: Any) -> list[dict[str, Any]]:
    """
    Validate structure and basic validity for the AI draft `categories` section only.
    """
    if not isinstance(categories_data, list):
        raise AIDraftSchemaValidationError("Categories section must be a list.")

    count = len(categories_data)
    if count < 2 or count > 5:
        raise AIDraftSchemaValidationError(
            "Categories list must contain between 2 and 5 items."
        )

    normalized_names: set[str] = set()
    validated: list[dict[str, Any]] = []

    for index, item in enumerate(categories_data):
        if not isinstance(item, Mapping):
            raise AIDraftSchemaValidationError(
                f"Category item at index {index} must be a mapping object."
            )

        if "name" not in item:
            raise AIDraftSchemaValidationError(
                f"Category item at index {index} is missing required field 'name'."
            )

        name = item["name"]
        if not isinstance(name, str):
            raise AIDraftSchemaValidationError(
                f"Category name at index {index} must be a string."
            )

        if not name.strip():
            raise AIDraftSchemaValidationError(
                f"Category name at index {index} must be a non-empty string."
            )

        normalized = _normalize_category_name(name)
        if normalized in normalized_names:
            raise AIDraftSchemaValidationError(
                f"Duplicate category name detected at index {index}: '{name}'."
            )
        normalized_names.add(normalized)
        validated.append(dict(item))

    return validated


def _normalize_sku(sku: str) -> str:
    return " ".join(sku.strip().split()).casefold()


def validate_products_section(
    products_data: Any,
    category_names: Any,
) -> list[dict[str, Any]]:
    """
    Validate structure and basic validity for the AI draft `products` section only.
    """
    if not isinstance(products_data, list):
        raise AIDraftSchemaValidationError("Products section must be a list.")

    products_count = len(products_data)
    if products_count < 2 or products_count > 4:
        raise AIDraftSchemaValidationError(
            "Products list must contain between 2 and 4 items."
        )

    if not isinstance(category_names, (list, set, tuple)):
        raise AIDraftSchemaValidationError(
            "category_names must be a list/set/tuple of category names."
        )

    normalized_category_names: set[str] = set()
    for name in category_names:
        if isinstance(name, str) and name.strip():
            normalized_category_names.add(_normalize_category_name(name))

    if not normalized_category_names:
        raise AIDraftSchemaValidationError(
            "category_names must contain at least one non-empty category name."
        )

    required_fields = {
        "name",
        "description",
        "price",
        "sku",
        "category_name",
        "stock_quantity",
        "image_url",
    }
    normalized_skus: set[str] = set()
    validated: list[dict[str, Any]] = []

    for index, item in enumerate(products_data):
        if not isinstance(item, Mapping):
            raise AIDraftSchemaValidationError(
                f"Product item at index {index} must be a mapping object."
            )

        for field in required_fields:
            if field not in item:
                raise AIDraftSchemaValidationError(
                    f"Product item at index {index} is missing required field '{field}'."
                )

        for field in ("name", "description", "sku", "category_name"):
            value = item[field]
            if not isinstance(value, str):
                raise AIDraftSchemaValidationError(
                    f"Product field '{field}' at index {index} must be a string."
                )
            if not value.strip():
                raise AIDraftSchemaValidationError(
                    f"Product field '{field}' at index {index} must be a non-empty string."
                )

        image_url = item["image_url"]
        if not isinstance(image_url, str):
            raise AIDraftSchemaValidationError(
                f"Product field 'image_url' at index {index} must be a string."
            )

        price = item["price"]
        if not isinstance(price, Real) or isinstance(price, bool):
            raise AIDraftSchemaValidationError(
                f"Product field 'price' at index {index} must be a number."
            )
        if price <= 0:
            raise AIDraftSchemaValidationError(
                f"Product field 'price' at index {index} must be greater than 0."
            )

        stock_quantity = item["stock_quantity"]
        if not isinstance(stock_quantity, int) or isinstance(stock_quantity, bool):
            raise AIDraftSchemaValidationError(
                f"Product field 'stock_quantity' at index {index} must be an integer."
            )
        if stock_quantity < 0:
            raise AIDraftSchemaValidationError(
                f"Product field 'stock_quantity' at index {index} must be >= 0."
            )

        normalized_sku = _normalize_sku(item["sku"])
        if normalized_sku in normalized_skus:
            raise AIDraftSchemaValidationError(
                f"Duplicate product SKU detected at index {index}: '{item['sku']}'."
            )
        normalized_skus.add(normalized_sku)

        normalized_category_name = _normalize_category_name(item["category_name"])
        if normalized_category_name not in normalized_category_names:
            raise AIDraftSchemaValidationError(
                f"Product category_name at index {index} does not match generated categories."
            )

        validated.append(dict(item))

    return validated


def detect_ai_response_mode(payload: Mapping[str, Any]) -> Literal["clarification", "draft_ready"]:
    """
    Detect AI response mode from clarification flags and enforce consistency.

    Rules:
    - clarification_needed == True  => clarification_questions must be non-empty
    - clarification_needed == False => clarification_questions must be empty
    """
    if not isinstance(payload, Mapping):
        raise AIDraftSchemaValidationError("Payload must be a mapping object.")

    if "clarification_needed" not in payload:
        raise AIDraftSchemaValidationError("Missing required key: 'clarification_needed'.")
    if "clarification_questions" not in payload:
        raise AIDraftSchemaValidationError("Missing required key: 'clarification_questions'.")

    clarification_needed = payload["clarification_needed"]
    clarification_questions = payload["clarification_questions"]

    if not isinstance(clarification_needed, bool):
        raise AIDraftSchemaValidationError("'clarification_needed' must be a boolean.")
    if not isinstance(clarification_questions, list):
        raise AIDraftSchemaValidationError("'clarification_questions' must be a list.")

    if clarification_needed and not clarification_questions:
        raise AIDraftSchemaValidationError(
            "Contradictory clarification state: 'clarification_needed' is true but "
            "'clarification_questions' is empty."
        )

    if not clarification_needed and clarification_questions:
        raise AIDraftSchemaValidationError(
            "Contradictory clarification state: 'clarification_needed' is false but "
            "'clarification_questions' is not empty."
        )

    if clarification_needed:
        expected_keys = {"question_key", "question_text", "options"}
        for index, question in enumerate(clarification_questions):
            if not isinstance(question, Mapping):
                raise AIDraftSchemaValidationError(
                    f"Clarification question at index {index} must be an object."
                )

            question_keys = set(question.keys())
            if not expected_keys.issubset(question_keys):
                raise AIDraftSchemaValidationError(
                    f"Clarification question at index {index} must contain required keys: "
                    "question_key, question_text, options."
                )

            question_key = question.get("question_key")
            if not isinstance(question_key, str) or not question_key.strip():
                raise AIDraftSchemaValidationError(
                    f"Clarification question 'question_key' at index {index} must be a non-empty string."
                )

            question_text = question.get("question_text")
            if not isinstance(question_text, str) or not question_text.strip():
                raise AIDraftSchemaValidationError(
                    f"Clarification question 'question_text' at index {index} must be a non-empty string."
                )

            options = question.get("options")
            if not isinstance(options, list):
                raise AIDraftSchemaValidationError(
                    f"Clarification question 'options' at index {index} must be a list."
                )

            if len(options) < 2 or len(options) > 5:
                raise AIDraftSchemaValidationError(
                    f"Clarification question 'options' at index {index} must contain between 2 and 5 items."
                )

            for option_index, option in enumerate(options):
                if not isinstance(option, str) or not option.strip():
                    raise AIDraftSchemaValidationError(
                        f"Clarification question option at index {index}:{option_index} must be a non-empty string."
                    )

    return "clarification" if clarification_needed else "draft_ready"


def build_ai_fallback_payload(
    clarification_questions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build the official clarification-style fallback payload for unusable AI responses.

    Decision note:
    - Fallback in AI Store Creation is clarification-style (not template-style).
    - The payload intentionally requests clarification with structured MCQ objects.
    """
    default_questions = [
        {
            "question_key": "store_type",
            "question_text": "What type of store do you want to create?",
            "options": ["Fashion", "Electronics", "Food & Grocery", "Other"],
        }
    ]
    questions = list(clarification_questions) if clarification_questions else default_questions
    fallback_payload = {
        "store": {},
        "store_settings": {},
        "theme": {},
        "categories": [],
        "products": [],
        "clarification_needed": True,
        "clarification_questions": questions,
    }

    # Keep fallback usable even if a custom questions list was malformed.
    try:
        detect_ai_response_mode(fallback_payload)
    except AIDraftSchemaValidationError:
        fallback_payload["clarification_questions"] = default_questions

    return fallback_payload
