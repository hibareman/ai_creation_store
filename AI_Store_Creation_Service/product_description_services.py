"""Business logic for AI-assisted product-description suggestions.

This module is the single service-layer entry point for the feature exposed later
through::

    POST /api/ai/stores/{store_id}/products/description/

Responsibilities
----------------
- Enforce authenticated owner and trusted-tenant access to the target store.
- Resolve the selected category from the same store and tenant.
- Validate the already-serialized input again at the service boundary.
- Call the configured AI provider using the dedicated product-description API.
- Parse and strictly validate the provider output against the frozen response
  contract.
- Write only a lightweight operational audit entry.

Non-responsibilities
--------------------
- This service never creates or updates a ``Product``.
- It never persists the generated description or ``additional_information``.
- It does not trust a client-supplied category name or language.
- It does not expose provider errors, prompts, or raw responses to the caller.

The returned description is therefore always a review-only suggestion with
``saved`` fixed to ``False``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import logging
from typing import Any, Mapping

from django.core.exceptions import ImproperlyConfigured

from categories.models import Category
from stores.models import Store

from .audit_services import _write_ai_audit_log
from .parsers import AIProviderParsingError, parse_provider_raw_response_to_dict
from .product_description_contracts import (
    PRODUCT_DESCRIPTION_MODE_GENERATE,
    PRODUCT_DESCRIPTION_MODE_IMPROVE,
    PRODUCT_DESCRIPTION_MODES,
)
from .product_description_serializers import (
    SUPPORTED_DETECTED_LANGUAGES,
    ProductDescriptionResponseSerializer,
)
from .providers import AIProviderContract, get_ai_provider_client


logger = logging.getLogger(__name__)

PRODUCT_DESCRIPTION_AUDIT_ACTION = "product_description"

_EXPECTED_AI_RESPONSE_FIELDS = frozenset(
    {
        "product_understanding",
        "generated_description",
        "improvement_summary",
        "suggested_information",
        "saved",
    }
)

# A conservative threshold used only to reject an obviously wrong-language AI
# response. Short or mixed commercial text is accepted to avoid rejecting valid
# brand names and technical terms.
_MIN_LANGUAGE_EVIDENCE_LETTERS = 20
_LANGUAGE_MISMATCH_RATIO = 1.5

_ARABIC_UNICODE_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


class ProductDescriptionServiceError(Exception):
    """Base exception with a stable public API error code and safe detail."""

    error_code = "invalid_product_data"
    default_detail = "The product-description request could not be completed."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = (detail or self.default_detail).strip()
        super().__init__(self.detail)

    def as_error_response(self) -> dict[str, str]:
        """Return the stable error body expected by the future API view."""

        return {
            "detail": self.detail,
            "error_code": self.error_code,
        }


class ProductDescriptionInvalidDataError(ProductDescriptionServiceError):
    error_code = "invalid_product_data"
    default_detail = "Complete the required product data before using AI."


class ProductDescriptionStoreAccessDeniedError(ProductDescriptionServiceError):
    error_code = "store_access_denied"
    default_detail = "You do not have access to this store."


class ProductDescriptionCategoryNotFoundError(ProductDescriptionServiceError):
    error_code = "category_not_found"
    default_detail = "The selected category does not belong to this store."


class ProductDescriptionAIUnavailableError(ProductDescriptionServiceError):
    error_code = "ai_service_unavailable"
    default_detail = (
        "The AI service is currently unavailable. Try again later or write the "
        "description manually."
    )


class ProductDescriptionInvalidAIResponseError(ProductDescriptionServiceError):
    error_code = "invalid_ai_response"
    default_detail = (
        "The AI service returned an unsuitable description. Please try again."
    )


def _positive_int_or_none(value: Any) -> int | None:
    """Normalize a positive integer without accepting booleans."""

    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized if normalized > 0 else None


def _normalize_non_empty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProductDescriptionInvalidDataError(
            f"{field_name} must be a text value."
        )
    normalized = value.strip()
    if not normalized:
        raise ProductDescriptionInvalidDataError(f"{field_name} is required.")
    return normalized


def _normalize_optional_text(value: Any, *, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProductDescriptionInvalidDataError(
            f"{field_name} must be a text value."
        )
    return value.strip()


def _normalize_positive_price(value: Any) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ProductDescriptionInvalidDataError(
            "price must be a valid positive number."
        ) from None

    if not price.is_finite() or price <= 0:
        raise ProductDescriptionInvalidDataError(
            "price must be greater than zero."
        )
    return price


def _normalize_request_data(validated_data: Mapping[str, Any]) -> dict[str, Any]:
    """Defensively normalize serializer output at the service boundary."""

    if not isinstance(validated_data, Mapping):
        raise ProductDescriptionInvalidDataError(
            "Validated product data must be an object."
        )

    mode = validated_data.get("mode")
    if mode not in PRODUCT_DESCRIPTION_MODES:
        raise ProductDescriptionInvalidDataError(
            "mode must be either 'generate' or 'improve'."
        )

    product_name = _normalize_non_empty_text(
        validated_data.get("product_name"),
        field_name="product_name",
    )
    category_id = _positive_int_or_none(validated_data.get("category_id"))
    if category_id is None:
        raise ProductDescriptionInvalidDataError(
            "category_id must be a positive integer."
        )

    current_description = _normalize_optional_text(
        validated_data.get("current_description", ""),
        field_name="current_description",
    )
    additional_information = _normalize_optional_text(
        validated_data.get("additional_information", ""),
        field_name="additional_information",
    )

    if mode == PRODUCT_DESCRIPTION_MODE_IMPROVE and not current_description:
        raise ProductDescriptionInvalidDataError(
            "current_description is required when mode is 'improve'."
        )

    detected_language = validated_data.get("detected_language")
    if detected_language not in SUPPORTED_DETECTED_LANGUAGES:
        raise ProductDescriptionInvalidDataError(
            "The backend could not determine a supported product language."
        )

    return {
        "mode": mode,
        "product_name": product_name,
        "category_id": category_id,
        "price": _normalize_positive_price(validated_data.get("price")),
        "current_description": current_description,
        "additional_information": additional_information,
        "detected_language": detected_language,
    }


def _resolve_owned_store(*, user: Any, tenant_id: Any, store_id: Any) -> Store:
    """Resolve the store with ownership and tenant isolation in one query.

    The same public error is used for authentication, tenant mismatch, missing
    store, and ownership mismatch. This prevents leaking whether another
    tenant's store exists.
    """

    normalized_tenant_id = _positive_int_or_none(tenant_id)
    normalized_store_id = _positive_int_or_none(store_id)
    normalized_user_id = _positive_int_or_none(getattr(user, "id", None))

    if (
        not bool(getattr(user, "is_authenticated", False))
        or normalized_tenant_id is None
        or normalized_store_id is None
        or normalized_user_id is None
        or _positive_int_or_none(getattr(user, "tenant_id", None))
        != normalized_tenant_id
    ):
        raise ProductDescriptionStoreAccessDeniedError()

    store = (
        Store.objects.filter(
            id=normalized_store_id,
            tenant_id=normalized_tenant_id,
            owner_id=normalized_user_id,
        )
        .only("id", "tenant_id", "owner_id")
        .first()
    )
    if store is None:
        raise ProductDescriptionStoreAccessDeniedError()
    return store


def _resolve_scoped_category(
    *,
    category_id: int,
    store: Store,
    tenant_id: int,
    user_id: int,
) -> Category:
    """Resolve a category only inside the authorized store and tenant."""

    category = (
        Category.objects.filter(
            id=category_id,
            store_id=store.id,
            tenant_id=tenant_id,
            store__tenant_id=tenant_id,
            store__owner_id=user_id,
        )
        .only("id", "name", "store_id", "tenant_id")
        .first()
    )
    if category is None:
        raise ProductDescriptionCategoryNotFoundError()

    category_name = getattr(category, "name", None)
    if not isinstance(category_name, str) or not category_name.strip():
        logger.error(
            "AI product-description category has no usable name. category_id=%s, "
            "store_id=%s, tenant_id=%s",
            category_id,
            store.id,
            tenant_id,
        )
        raise ProductDescriptionInvalidDataError(
            "The selected category does not have a valid name."
        )

    return category


def _count_supported_script_letters(text: str) -> tuple[int, int]:
    arabic_count = 0
    english_count = 0

    for character in text:
        if not character.isalpha():
            continue
        codepoint = ord(character)
        if any(start <= codepoint <= end for start, end in _ARABIC_UNICODE_RANGES):
            arabic_count += 1
        elif ("A" <= character <= "Z") or ("a" <= character <= "z"):
            english_count += 1

    return arabic_count, english_count


def _response_has_obvious_language_mismatch(
    *, payload: Mapping[str, Any], expected_language: str
) -> bool:
    """Detect only strong Arabic/English response-language mismatches."""

    combined_text = "\n".join(
        str(payload.get(field_name, ""))
        for field_name in (
            "product_understanding",
            "generated_description",
            "improvement_summary",
            "suggested_information",
        )
    )
    arabic_count, english_count = _count_supported_script_letters(combined_text)
    total_evidence = arabic_count + english_count

    if total_evidence < _MIN_LANGUAGE_EVIDENCE_LETTERS:
        return False

    if expected_language == "ar":
        return english_count > arabic_count * _LANGUAGE_MISMATCH_RATIO
    return arabic_count > english_count * _LANGUAGE_MISMATCH_RATIO


def _normalized_text_for_comparison(value: str) -> str:
    return " ".join(value.casefold().split())


def _validate_ai_payload(
    *,
    payload: Mapping[str, Any],
    mode: str,
    current_description: str,
    detected_language: str,
) -> dict[str, Any]:
    """Enforce exact output fields, DRF constraints, and semantic invariants."""

    if not isinstance(payload, Mapping):
        raise ProductDescriptionInvalidAIResponseError()

    actual_fields = frozenset(payload.keys())
    if actual_fields != _EXPECTED_AI_RESPONSE_FIELDS:
        missing = sorted(_EXPECTED_AI_RESPONSE_FIELDS - actual_fields)
        unexpected = sorted(actual_fields - _EXPECTED_AI_RESPONSE_FIELDS)
        logger.warning(
            "Invalid AI product-description response fields. missing=%s unexpected=%s",
            missing,
            unexpected,
        )
        raise ProductDescriptionInvalidAIResponseError()

    response_serializer = ProductDescriptionResponseSerializer(data=dict(payload))
    if not response_serializer.is_valid():
        logger.warning(
            "AI product-description response failed schema validation. errors=%s",
            response_serializer.errors,
        )
        raise ProductDescriptionInvalidAIResponseError()

    result = dict(response_serializer.validated_data)

    if _response_has_obvious_language_mismatch(
        payload=result,
        expected_language=detected_language,
    ):
        logger.warning(
            "AI product-description response language mismatch. expected=%s",
            detected_language,
        )
        raise ProductDescriptionInvalidAIResponseError(
            "The AI response did not match the product language. Please try again."
        )

    if mode == PRODUCT_DESCRIPTION_MODE_IMPROVE:
        original = _normalized_text_for_comparison(current_description)
        generated = _normalized_text_for_comparison(result["generated_description"])
        if original and original == generated:
            logger.warning(
                "AI product-description improve mode returned unchanged text."
            )
            raise ProductDescriptionInvalidAIResponseError(
                "The AI did not produce a meaningful improvement. Please try again."
            )

    # Preserve the non-persistence guarantee explicitly even though the response
    # serializer already rejects any value other than False.
    result["saved"] = False
    return result


def _audit(
    *,
    tenant_id: Any,
    store_id: Any,
    user: Any,
    status: str,
    message: str,
) -> None:
    _write_ai_audit_log(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_id=getattr(user, "id", None),
        action=PRODUCT_DESCRIPTION_AUDIT_ACTION,
        status=status,
        message=message,
    )


def generate_product_description_suggestion(
    *,
    user: Any,
    tenant_id: int | None,
    store_id: int,
    validated_data: Mapping[str, Any],
    provider: AIProviderContract | None = None,
) -> dict[str, Any]:
    """Generate a validated, review-only product-description suggestion.

    Parameters
    ----------
    user:
        Authenticated Store Owner.
    tenant_id:
        Trusted tenant identifier supplied by authentication/middleware, never
        by the request body.
    store_id:
        Store path parameter.
    validated_data:
        ``ProductDescriptionRequestSerializer.validated_data``. It must include
        the backend-derived ``detected_language`` value.
    provider:
        Optional provider injection point for unit tests. Production callers
        should omit it so the configured provider factory is used.

    Returns
    -------
    dict
        Exactly the frozen success contract. ``saved`` is always ``False``.

    Raises
    ------
    ProductDescriptionServiceError
        A typed, public-safe service exception carrying one of the frozen error
        codes. The future API view should catch this base class and return
        ``exc.as_error_response()``.
    """

    request_data = _normalize_request_data(validated_data)
    store = _resolve_owned_store(user=user, tenant_id=tenant_id, store_id=store_id)

    normalized_tenant_id = int(store.tenant_id)
    normalized_user_id = int(store.owner_id)
    category = _resolve_scoped_category(
        category_id=request_data["category_id"],
        store=store,
        tenant_id=normalized_tenant_id,
        user_id=normalized_user_id,
    )
    category_name = category.name.strip()

    audit_context = (
        f"mode={request_data['mode']}; language={request_data['detected_language']}; "
        f"category_id={category.id}; no_product_data_saved=true"
    )
    _audit(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        user=user,
        status="requested",
        message=audit_context,
    )

    try:
        ai_provider = provider or get_ai_provider_client()
        raw_response = ai_provider.generate_product_description(
            mode=request_data["mode"],
            product_name=request_data["product_name"],
            category_name=category_name,
            price=request_data["price"],
            current_description=request_data["current_description"],
            additional_information=request_data["additional_information"],
            detected_language=request_data["detected_language"],
        )
    except json.JSONDecodeError as exc:
        logger.warning(
            "AI product-description provider returned malformed JSON. store_id=%s",
            store.id,
            exc_info=True,
        )
        _audit(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            user=user,
            status="failed",
            message="Provider returned malformed JSON.",
        )
        raise ProductDescriptionInvalidAIResponseError() from exc
    except (ImproperlyConfigured, RuntimeError, TimeoutError, ConnectionError, OSError) as exc:
        logger.warning(
            "AI product-description provider unavailable. store_id=%s reason=%s",
            store.id,
            str(exc),
        )
        _audit(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            user=user,
            status="failed",
            message=f"Provider unavailable: {type(exc).__name__}",
        )
        raise ProductDescriptionAIUnavailableError() from exc
    except ProductDescriptionServiceError:
        raise
    except Exception as exc:  # external provider boundary; do not leak internals
        logger.exception(
            "Unexpected AI product-description provider failure. store_id=%s",
            store.id,
        )
        _audit(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            user=user,
            status="failed",
            message=f"Unexpected provider failure: {type(exc).__name__}",
        )
        raise ProductDescriptionAIUnavailableError() from exc

    try:
        parsed_payload = parse_provider_raw_response_to_dict(raw_response)
        result = _validate_ai_payload(
            payload=parsed_payload,
            mode=request_data["mode"],
            current_description=request_data["current_description"],
            detected_language=request_data["detected_language"],
        )
    except AIProviderParsingError as exc:
        logger.warning(
            "AI product-description response parsing failed. store_id=%s reason=%s",
            store.id,
            str(exc),
        )
        _audit(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            user=user,
            status="failed",
            message="Provider response could not be parsed.",
        )
        raise ProductDescriptionInvalidAIResponseError() from exc
    except ProductDescriptionInvalidAIResponseError as exc:
        _audit(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            user=user,
            status="failed",
            message="Provider response failed product-description validation.",
        )
        raise

    _audit(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        user=user,
        status="completed",
        message=audit_context,
    )

    logger.info(
        "AI product-description suggestion completed. store_id=%s tenant_id=%s "
        "actor_id=%s mode=%s language=%s saved=false",
        store.id,
        normalized_tenant_id,
        getattr(user, "id", None),
        request_data["mode"],
        request_data["detected_language"],
    )
    return result


__all__ = [
    "PRODUCT_DESCRIPTION_AUDIT_ACTION",
    "ProductDescriptionAIUnavailableError",
    "ProductDescriptionCategoryNotFoundError",
    "ProductDescriptionInvalidAIResponseError",
    "ProductDescriptionInvalidDataError",
    "ProductDescriptionServiceError",
    "ProductDescriptionStoreAccessDeniedError",
    "generate_product_description_suggestion",
]
