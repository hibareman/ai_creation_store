"""Serializers for the AI-assisted product-description API.

This module implements the request, success-response, and error-response
contracts frozen in :mod:`product_description_contracts`.

The serializers are intentionally limited to transport-level validation and
normalization. They do not access the database, resolve stores or categories,
call the AI provider, or persist product data. Ownership, tenant isolation,
category scoping, provider execution, and audit logging belong to the service
layer implemented in later tasks.

The request does not accept a language chosen by the client. The backend derives
``detected_language`` from the textual product data and passes that internal
value to the prompt/provider layer. Only Arabic (``ar``) and English (``en``)
are currently supported by this feature.
"""

from __future__ import annotations

from collections.abc import Iterable

from rest_framework import serializers

from .product_description_contracts import (
    PRODUCT_DESCRIPTION_MODE_IMPROVE,
    PRODUCT_DESCRIPTION_MODES,
)


# These limits protect the provider context and establish a stable API contract.
# The generated description limit is intentionally stricter than Product's
# TextField because this feature returns a concise, reviewable sales description.
PRODUCT_NAME_MAX_LENGTH = 255
CURRENT_DESCRIPTION_MAX_LENGTH = 10_000
ADDITIONAL_INFORMATION_MAX_LENGTH = 3_000

GENERATED_DESCRIPTION_MIN_LENGTH = 80
GENERATED_DESCRIPTION_MAX_LENGTH = 1_000
PRODUCT_UNDERSTANDING_MAX_LENGTH = 1_200
IMPROVEMENT_SUMMARY_MAX_LENGTH = 1_200
SUGGESTED_INFORMATION_MAX_LENGTH = 2_000

DETECTED_LANGUAGE_AR = "ar"
DETECTED_LANGUAGE_EN = "en"
SUPPORTED_DETECTED_LANGUAGES = (
    DETECTED_LANGUAGE_AR,
    DETECTED_LANGUAGE_EN,
)

# Arabic characters can occur in the basic Arabic block as well as presentation
# forms and supplementary Arabic blocks. Checking all of these ranges prevents
# false English detection for valid Arabic product text copied from different
# editors or fonts.
_ARABIC_UNICODE_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _is_arabic_letter(character: str) -> bool:
    if not character.isalpha():
        return False
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _ARABIC_UNICODE_RANGES)


def _is_english_letter(character: str) -> bool:
    """Return true only for ASCII English letters.

    The feature currently supports Arabic and English only. Digits, prices,
    punctuation, emojis, and symbols are deliberately ignored because they do
    not provide reliable language evidence.
    """

    return ("A" <= character <= "Z") or ("a" <= character <= "z")


def _count_language_letters(texts: Iterable[str]) -> tuple[int, int]:
    arabic_count = 0
    english_count = 0

    for text in texts:
        for character in text or "":
            if _is_arabic_letter(character):
                arabic_count += 1
            elif _is_english_letter(character):
                english_count += 1

    return arabic_count, english_count


def detect_product_content_language(
    *,
    product_name: str,
    current_description: str = "",
    additional_information: str = "",
) -> str:
    """Detect ``ar`` or ``en`` from product text using dominant script.

    Detection rules:
    1. Count Arabic and English letters across the product name, current
       description, and additional information.
    2. Select the dominant language.
    3. On a tie, use the product name as the tie-breaker because it is the
       strongest product-identity signal.
    4. If there is still no usable language evidence, default to English. The
       product name is required, so this fallback should be uncommon.

    This is intentionally deterministic backend logic and does not require an
    additional AI call merely to identify Arabic versus English.
    """

    all_arabic, all_english = _count_language_letters(
        (product_name, current_description, additional_information)
    )

    if all_arabic > all_english:
        return DETECTED_LANGUAGE_AR
    if all_english > all_arabic:
        return DETECTED_LANGUAGE_EN

    name_arabic, name_english = _count_language_letters((product_name,))
    if name_arabic > name_english:
        return DETECTED_LANGUAGE_AR
    if name_english > name_arabic:
        return DETECTED_LANGUAGE_EN

    return DETECTED_LANGUAGE_EN


class ProductDescriptionRequestSerializer(serializers.Serializer):
    """Validate input for generating, improving, or merging a description.

    ``additional_information`` is temporary AI context. It is accepted from the
    editable UI field and must never be interpreted as a persistent product
    attribute by this serializer or by later service code.

    ``detected_language`` is added to ``validated_data`` by the backend and is
    not accepted as a public request field.
    """

    mode = serializers.ChoiceField(choices=PRODUCT_DESCRIPTION_MODES)
    product_name = serializers.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH,
        allow_blank=False,
        trim_whitespace=True,
    )
    category_id = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        coerce_to_string=False,
    )
    current_description = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        max_length=CURRENT_DESCRIPTION_MAX_LENGTH,
        trim_whitespace=True,
    )
    additional_information = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        max_length=ADDITIONAL_INFORMATION_MAX_LENGTH,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        """Reject client-controlled language fields explicitly.

        Rejecting rather than silently ignoring these keys keeps the API
        contract unambiguous: output language is always selected by backend
        detection from the submitted product content.
        """

        client_controlled_language_fields = {
            field_name: (
                "This field is determined automatically by the backend from "
                "the product text."
            )
            for field_name in ("language", "detected_language")
            if field_name in data
        }
        if client_controlled_language_fields:
            raise serializers.ValidationError(client_controlled_language_fields)

        return super().to_internal_value(data)

    def validate_product_name(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise serializers.ValidationError("Product name is required.")
        return normalized

    def validate(self, attrs: dict) -> dict:
        """Apply mode rules, normalize text, and derive output language."""

        mode = attrs["mode"]
        current_description = attrs.get("current_description", "").strip()
        additional_information = attrs.get("additional_information", "").strip()

        if mode == PRODUCT_DESCRIPTION_MODE_IMPROVE and not current_description:
            raise serializers.ValidationError(
                {
                    "current_description": (
                        "Current description is required when mode is 'improve'."
                    )
                }
            )

        attrs["current_description"] = current_description
        attrs["additional_information"] = additional_information
        attrs["detected_language"] = detect_product_content_language(
            product_name=attrs["product_name"],
            current_description=current_description,
            additional_information=additional_information,
        )

        return attrs


class ProductDescriptionResponseSerializer(serializers.Serializer):
    """Validate the AI suggestion returned for Store Owner review.

    This serializer enforces the agreed output length and the non-persistence
    guarantee. The service layer should validate provider output with this
    serializer before returning it from the API.
    """

    product_understanding = serializers.CharField(
        allow_blank=False,
        min_length=10,
        max_length=PRODUCT_UNDERSTANDING_MAX_LENGTH,
        trim_whitespace=True,
    )
    generated_description = serializers.CharField(
        allow_blank=False,
        min_length=GENERATED_DESCRIPTION_MIN_LENGTH,
        max_length=GENERATED_DESCRIPTION_MAX_LENGTH,
        trim_whitespace=True,
    )
    improvement_summary = serializers.CharField(
        allow_blank=False,
        min_length=10,
        max_length=IMPROVEMENT_SUMMARY_MAX_LENGTH,
        trim_whitespace=True,
    )
    suggested_information = serializers.CharField(
        allow_blank=False,
        min_length=2,
        max_length=SUGGESTED_INFORMATION_MAX_LENGTH,
        trim_whitespace=True,
    )
    saved = serializers.BooleanField()

    def validate_saved(self, value: bool) -> bool:
        if value is not False:
            raise serializers.ValidationError(
                "AI-generated descriptions are suggestions and must not be saved automatically."
            )
        return False


class ProductDescriptionErrorResponseSerializer(serializers.Serializer):
    """Document and validate the stable error response shape."""

    ERROR_CODES = (
        "invalid_product_data",
        "store_access_denied",
        "category_not_found",
        "ai_service_unavailable",
        "invalid_ai_response",
    )

    detail = serializers.CharField(allow_blank=False, trim_whitespace=True)
    error_code = serializers.ChoiceField(choices=ERROR_CODES)


__all__ = [
    "ADDITIONAL_INFORMATION_MAX_LENGTH",
    "CURRENT_DESCRIPTION_MAX_LENGTH",
    "DETECTED_LANGUAGE_AR",
    "DETECTED_LANGUAGE_EN",
    "GENERATED_DESCRIPTION_MAX_LENGTH",
    "GENERATED_DESCRIPTION_MIN_LENGTH",
    "IMPROVEMENT_SUMMARY_MAX_LENGTH",
    "PRODUCT_NAME_MAX_LENGTH",
    "PRODUCT_UNDERSTANDING_MAX_LENGTH",
    "SUPPORTED_DETECTED_LANGUAGES",
    "SUGGESTED_INFORMATION_MAX_LENGTH",
    "ProductDescriptionErrorResponseSerializer",
    "ProductDescriptionRequestSerializer",
    "ProductDescriptionResponseSerializer",
    "detect_product_content_language",
]
