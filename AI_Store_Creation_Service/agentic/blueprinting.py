"""Deterministic Store Blueprint construction for the controlled agentic workflow.

The backend owns the locked personalization constraints.  The blueprint is built
only from explicit description facts and confirmed clarification facts; it does
not call a provider and it never invents major merchant decisions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..parsers import parse_provider_raw_response_to_dict
from ..providers import get_ai_provider_client

from .personalization import (
    CORE_PERSONALIZATION_KEYS,
    get_missing_core_personalization_keys,
    merge_personalization_facts,
)

_BLUEPRINT_KEYS = {
    "normalized_description",
    "product_offering",
    "catalog_scope",
    "target_audience",
    "target_market",
    "customer_problem",
    "unique_value_proposition",
    "price_positioning",
    "brand_personality",
    "visual_preferences",
    "language",
    "currency",
    "category_strategy",
    "product_strategy",
    "customer_fit_strategy",
    "brand_voice_strategy",
    "pricing_strategy",
    "visual_strategy",
    "available_theme_templates",
    "locked_constraints",
    "source_context",
}

_LANGUAGE_ALIASES = {
    "ar": "ar",
    "arabic": "ar",
    "العربية": "ar",
    "اللغة العربية": "ar",
    "عربي": "ar",
    "عربية": "ar",
    "en": "en",
    "english": "en",
    "الإنجليزية": "en",
    "الانجليزية": "en",
    "إنجليزي": "en",
    "انجليزي": "en",
}

_CURRENCY_ALIASES = {
    "usd": "USD",
    "us dollar": "USD",
    "dollar": "USD",
    "دولار": "USD",
    "الدولار": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "يورو": "EUR",
    "syp": "SYP",
    "syrian pound": "SYP",
    "syrian lira": "SYP",
    "ليرة سورية": "SYP",
    "الليرة السورية": "SYP",
    "sar": "SAR",
    "saudi riyal": "SAR",
    "ريال سعودي": "SAR",
    "الريال السعودي": "SAR",
    "الريال": "SAR",
    "aed": "AED",
    "uae dirham": "AED",
    "emirati dirham": "AED",
    "درهم إماراتي": "AED",
    "egp": "EGP",
    "egyptian pound": "EGP",
    "جنيه مصري": "EGP",
    "gbp": "GBP",
    "british pound": "GBP",
    "pound sterling": "GBP",
    "try": "TRY",
    "turkish lira": "TRY",
    "ليرة تركية": "TRY",
    "jod": "JOD",
    "jordanian dinar": "JOD",
    "دينار أردني": "JOD",
    "kwd": "KWD",
    "kuwaiti dinar": "KWD",
    "دينار كويتي": "KWD",
    "qar": "QAR",
    "qatari riyal": "QAR",
    "ريال قطري": "QAR",
}

_CURRENCY_CODES = frozenset(_CURRENCY_ALIASES.values())


class AIBlueprintValidationError(ValueError):
    """Raised when a blueprint cannot be created without inventing facts."""

    def __init__(self, message: str, *, repair_attempt_count: int = 0) -> None:
        super().__init__(message)
        self.repair_attempt_count = max(0, int(repair_attempt_count))


def build_store_blueprint(
    *,
    normalized_description: Any,
    description_personalization_facts: Any,
    clarification_facts: Any,
    clarification_history: Any,
    effective_personalization_context: Any,
    available_theme_templates: Any,
    personalization_core_complete: Any,
    missing_core_personalization_keys: Any,
    ambiguous_personalization_keys: Any,
    additional_blocking_missing_information: Any,
) -> dict[str, Any]:
    """Build a JSON-safe blueprint from complete, explicit personalization facts."""

    description = _normalize_required_text(
        normalized_description,
        field_name="normalized_description",
        max_length=4000,
    )
    description_facts = _normalize_fact_mapping(
        description_personalization_facts,
        field_name="description_personalization_facts",
    )
    confirmed_facts = _normalize_fact_mapping(
        clarification_facts,
        field_name="clarification_facts",
    )
    history = _normalize_history(clarification_history)
    effective = _normalize_fact_mapping(
        effective_personalization_context,
        field_name="effective_personalization_context",
    )
    templates = _normalize_theme_templates(available_theme_templates)

    if personalization_core_complete is not True:
        raise AIBlueprintValidationError(
            "Blueprint requires complete core personalization facts."
        )
    if _normalize_key_list(
        missing_core_personalization_keys,
        field_name="missing_core_personalization_keys",
    ):
        raise AIBlueprintValidationError("Blueprint cannot contain missing core facts.")
    if _normalize_key_list(
        ambiguous_personalization_keys,
        field_name="ambiguous_personalization_keys",
    ):
        raise AIBlueprintValidationError("Blueprint cannot contain ambiguous core facts.")
    if _normalize_key_list(
        additional_blocking_missing_information,
        field_name="additional_blocking_missing_information",
    ):
        raise AIBlueprintValidationError(
            "Blueprint cannot be created while blocking information remains."
        )

    merged = merge_personalization_facts(description_facts, confirmed_facts)
    missing = get_missing_core_personalization_keys(merged)
    if missing:
        raise AIBlueprintValidationError(
            "Blueprint requires all canonical personalization facts."
        )
    if effective != merged:
        raise AIBlueprintValidationError(
            "Effective personalization context must equal the deterministic merged facts."
        )

    language, currency = resolve_language_currency(effective["language_currency"])
    locked_constraints = deepcopy(effective)
    locked_constraints["language"] = language
    locked_constraints["currency"] = currency

    blueprint = {
        "normalized_description": description,
        "product_offering": deepcopy(effective["product_offering"]),
        "catalog_scope": deepcopy(effective["catalog_scope"]),
        "target_audience": deepcopy(effective["target_audience"]),
        "target_market": deepcopy(effective["target_market"]),
        "customer_problem": deepcopy(effective["customer_problem"]),
        "unique_value_proposition": deepcopy(
            effective["unique_value_proposition"]
        ),
        "price_positioning": deepcopy(effective["price_positioning"]),
        "brand_personality": deepcopy(effective["brand_personality"]),
        "visual_preferences": deepcopy(effective["visual_preferences"]),
        "language": language,
        "currency": currency,
        "category_strategy": (
            "Keep every category strictly within the confirmed product offering "
            f"({_display(effective['product_offering'])}) and catalog scope "
            f"({_display(effective['catalog_scope'])})."
        ),
        "product_strategy": (
            "Generate products only for the confirmed offering and catalog scope; "
            "do not broaden the store into unrelated product domains."
        ),
        "customer_fit_strategy": (
            "Products and descriptions must serve the confirmed audience "
            f"({_display(effective['target_audience'])}) and address "
            f"({_display(effective['customer_problem'])}) in the confirmed market "
            f"({_display(effective['target_market'])})."
        ),
        "brand_voice_strategy": (
            "Use wording and merchandising consistent with the confirmed brand "
            f"personality: {_display(effective['brand_personality'])}."
        ),
        "pricing_strategy": (
            "Keep product selection, descriptions, and price direction consistent "
            f"with {_display(effective['price_positioning'])}."
        ),
        "visual_strategy": (
            "Choose an available theme and visual values consistent with the "
            f"confirmed preferences: {_display(effective['visual_preferences'])}."
        ),
        "available_theme_templates": templates,
        "locked_constraints": locked_constraints,
        "source_context": {
            "description_personalization_facts": description_facts,
            "clarification_facts": confirmed_facts,
            "clarification_history": history,
            "effective_personalization_context": effective,
        },
    }
    return validate_store_blueprint(
        blueprint,
        effective_personalization_context=effective,
        available_theme_templates=templates,
    )


def validate_store_blueprint(
    blueprint: Any,
    *,
    effective_personalization_context: Any,
    available_theme_templates: Any,
) -> dict[str, Any]:
    """Validate AI-authored strategy while canonicalizing backend-owned facts.

    The model may express language/currency and locked facts in different natural
    forms.  Those fields are not trusted as free-form AI output: the backend
    resolves them once, then injects the canonical values into the final
    Blueprint.  This prevents harmless wording differences from triggering a
    repair loop while still protecting merchant-confirmed constraints.
    """

    if not isinstance(blueprint, Mapping):
        raise AIBlueprintValidationError("Store blueprint must be an object.")
    normalized = dict(deepcopy(blueprint))
    _assert_json_serializable(normalized)

    # Require the AI-owned strategic fields. Backend-owned fields are injected
    # below and therefore need not be echoed perfectly by the provider.
    required_ai_fields = {
        "normalized_description",
        "category_strategy",
        "product_strategy",
        "customer_fit_strategy",
        "brand_voice_strategy",
        "pricing_strategy",
        "visual_strategy",
    }
    missing_ai_fields = required_ai_fields.difference(normalized)
    if missing_ai_fields:
        raise AIBlueprintValidationError(
            "Store blueprint is missing required strategy fields: "
            + ", ".join(sorted(missing_ai_fields))
        )

    effective = _normalize_fact_mapping(
        effective_personalization_context,
        field_name="effective_personalization_context",
    )
    if get_missing_core_personalization_keys(effective):
        raise AIBlueprintValidationError("Store blueprint context is incomplete.")

    language, currency = resolve_language_currency(
        effective.get("language_currency"),
        fallback_language=normalized.get("language"),
        fallback_currency=normalized.get("currency"),
    )
    templates = _normalize_theme_templates(available_theme_templates)

    # Canonicalize every backend-owned field. The AI is allowed to author the
    # six strategy fields, but cannot alter confirmed merchant facts.
    for key in CORE_PERSONALIZATION_KEYS[:-1]:
        normalized[key] = deepcopy(effective[key])
    normalized["language"] = language
    normalized["currency"] = currency
    normalized["available_theme_templates"] = templates

    locked = deepcopy(effective)
    locked["language"] = language
    locked["currency"] = currency
    normalized["locked_constraints"] = locked

    existing_source = normalized.get("source_context")
    if not isinstance(existing_source, Mapping):
        existing_source = {}
    normalized["source_context"] = {
        "description_personalization_facts": deepcopy(
            existing_source.get("description_personalization_facts", {})
        ),
        "clarification_facts": deepcopy(
            existing_source.get("clarification_facts", {})
        ),
        "clarification_history": deepcopy(
            existing_source.get("clarification_history", [])
        ),
        "effective_personalization_context": deepcopy(effective),
    }

    _normalize_required_text(
        normalized.get("normalized_description"),
        field_name="normalized_description",
        max_length=4000,
    )
    for strategy_key in (
        "category_strategy",
        "product_strategy",
        "customer_fit_strategy",
        "brand_voice_strategy",
        "pricing_strategy",
        "visual_strategy",
    ):
        normalized[strategy_key] = _normalize_required_text(
            normalized.get(strategy_key),
            field_name=strategy_key,
            max_length=1200,
        )

    # Drop provider extras and return the exact application contract.
    normalized = {key: normalized[key] for key in _BLUEPRINT_KEYS}
    return _json_copy(normalized)


def resolve_language_currency(
    value: Any,
    *,
    fallback_language: Any = None,
    fallback_currency: Any = None,
) -> tuple[str, str]:
    """Resolve language/currency from flexible semantic output.

    Accepts an object, a sequence, or natural-language text.  Canonical AI
    fields may be used only as fallbacks when the combined core fact omits one
    side.  Returned values are always normalized application codes.
    """

    language = ""
    currency = ""

    if isinstance(value, Mapping):
        language = _normalize_language(
            value.get("language")
            or value.get("language_code")
            or value.get("locale")
            or value.get("store_language")
        )
        currency = _normalize_currency(
            value.get("currency")
            or value.get("currency_code")
            or value.get("store_currency")
        )
        if not language or not currency:
            text = " ".join(
                str(item) for item in value.values()
                if isinstance(item, (str, int, float))
            )
            parsed_language, parsed_currency = _parse_language_currency_text(text)
            language = language or parsed_language
            currency = currency or parsed_currency
    elif isinstance(value, (list, tuple, set)):
        text = " / ".join(str(item) for item in value)
        language, currency = _parse_language_currency_text(text)
    elif isinstance(value, str):
        text = " ".join(value.strip().split())
        if not text:
            raise AIBlueprintValidationError("language_currency cannot be blank.")
        # Handle JSON encoded objects occasionally returned by providers.
        if text.startswith("{"):
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, Mapping):
                return resolve_language_currency(
                    decoded,
                    fallback_language=fallback_language,
                    fallback_currency=fallback_currency,
                )
        language, currency = _parse_language_currency_text(text)
    elif value is not None:
        language, currency = _parse_language_currency_text(str(value))

    language = language or _normalize_language(fallback_language)
    currency = currency or _normalize_currency(fallback_currency)

    if not language or not currency:
        raise AIBlueprintValidationError(
            "language_currency must identify a supported language and currency."
        )
    return language, currency


def _parse_language_currency_text(value: str) -> tuple[str, str]:
    text = " ".join(str(value).strip().split())
    folded = text.casefold()

    language = ""
    for alias, code in sorted(
        _LANGUAGE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if _contains_term(folded, alias.casefold()):
            language = code
            break

    currency = ""
    for alias, code in sorted(
        _CURRENCY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if _contains_term(folded, alias.casefold()):
            currency = code
            break
    if not currency:
        for token in re.findall(r"(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])", text):
            candidate = token.upper()
            if candidate in _CURRENCY_CODES:
                currency = candidate
                break
    return language, currency


def _contains_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9 ]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _normalize_language(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _LANGUAGE_ALIASES.get(" ".join(value.strip().split()).casefold(), "")


def _normalize_currency(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.strip().split())
    alias = _CURRENCY_ALIASES.get(normalized.casefold())
    if alias:
        return alias
    code = normalized.upper()
    return code if code in _CURRENCY_CODES else ""


def _normalize_required_text(value: Any, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise AIBlueprintValidationError(f"{field_name} must be a string.")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise AIBlueprintValidationError(f"{field_name} must be non-empty.")
    if len(normalized) > max_length:
        raise AIBlueprintValidationError(f"{field_name} is too long.")
    return normalized


def _normalize_fact_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AIBlueprintValidationError(f"{field_name} must be an object.")
    copied = dict(deepcopy(value))
    _assert_json_serializable(copied)
    normalized: dict[str, Any] = {}
    for key, fact in copied.items():
        if key not in CORE_PERSONALIZATION_KEYS:
            continue
        if isinstance(fact, str):
            clean = " ".join(fact.strip().split())
            if clean:
                normalized[key] = clean
        elif fact is not None and fact != [] and fact != {}:
            normalized[key] = deepcopy(fact)
    return normalized


def _normalize_key_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AIBlueprintValidationError(f"{field_name} must be a list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AIBlueprintValidationError(f"{field_name} must contain strings.")
        key = item.strip()
        if key not in seen:
            seen.add(key)
            normalized.append(key)
    return normalized


def _normalize_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AIBlueprintValidationError("clarification_history must be a list.")
    history = deepcopy(value)
    _assert_json_serializable(history)
    if not all(isinstance(item, Mapping) for item in history):
        raise AIBlueprintValidationError(
            "clarification_history rounds must be objects."
        )
    return [dict(item) for item in history]


def _normalize_theme_templates(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AIBlueprintValidationError(
            "available_theme_templates must be a list."
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise AIBlueprintValidationError("Theme template names must be strings.")
        name = " ".join(item.strip().split())
        if not name:
            raise AIBlueprintValidationError(
                "Theme template names must be non-empty."
            )
        if name not in seen:
            seen.add(name)
            normalized.append(name)
    if not normalized:
        raise AIBlueprintValidationError(
            "At least one available theme template is required."
        )
    return normalized


def _display(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _assert_json_serializable(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AIBlueprintValidationError(
            "Blueprint context must be JSON-serializable."
        ) from exc


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


__all__ = [
    "AIBlueprintValidationError",
    "build_store_blueprint",
    "resolve_language_currency",
    "validate_store_blueprint",
    "generate_ai_store_blueprint",
]


def generate_ai_store_blueprint(
    *, tenant_id: int, store_id: int, normalized_description: str,
    effective_personalization_context: Mapping[str, Any],
    clarification_history: list[dict[str, Any]],
    available_theme_templates: list[str], max_repair_attempts: int = 3,
) -> tuple[dict[str, Any], int]:
    """Call AI, validate its Blueprint, and repair invalid output up to the limit."""
    provider = get_ai_provider_client()
    raw = provider.generate_store_blueprint(
        tenant_id=tenant_id, store_id=store_id,
        normalized_description=normalized_description,
        effective_personalization_context=deepcopy(dict(effective_personalization_context)),
        clarification_history=deepcopy(clarification_history),
        available_theme_templates=deepcopy(available_theme_templates),
    )
    attempts = 0
    candidate: dict[str, Any] = {}
    last_error: Exception | None = None
    while True:
        try:
            candidate = parse_provider_raw_response_to_dict(raw)
            validated = validate_store_blueprint(
                candidate, effective_personalization_context=effective_personalization_context,
                available_theme_templates=available_theme_templates,
            )
            return validated, attempts
        except (Exception,) as exc:
            last_error = exc
            if attempts >= max_repair_attempts:
                raise AIBlueprintValidationError(
                    f"Blueprint remained invalid after {attempts} repair attempts: {exc}",
                    repair_attempt_count=attempts,
                ) from exc
            attempts += 1
            errors = [{
                "path": "$",
                "code": "invalid_json" if not candidate else "invalid_blueprint",
                "message": str(exc),
                "repairable": True,
            }]
            raw = provider.repair_store_blueprint(
                tenant_id=tenant_id, store_id=store_id, invalid_blueprint=deepcopy(candidate),
                validation_errors=errors,
                effective_personalization_context=deepcopy(dict(effective_personalization_context)),
                available_theme_templates=deepcopy(available_theme_templates),
            )
