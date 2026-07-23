"""Stable API contract for AI-assisted product descriptions.

This module freezes the public request/response contract before serializers,
provider integration, service logic, views, and URL registration are added.
It contains no database access and does not call the AI provider.

Endpoint (registered in a later implementation task):
    POST /api/ai/stores/{store_id}/products/description/

The same endpoint supports three user interactions:
- Generate a new description: ``mode='generate'``.
- Improve an existing description: ``mode='improve'``.
- Merge extra information and improve again: send the current displayed
  description with ``additional_information`` using ``mode='improve'``.

The endpoint only returns a suggestion. It never persists a Product or changes
its current description. The agreed response therefore always contains
``saved: false``.
"""

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Endpoint identity
# ---------------------------------------------------------------------------

PRODUCT_DESCRIPTION_ENDPOINT_PATH: Final[str] = (
    "stores/<int:store_id>/products/description/"
)
PRODUCT_DESCRIPTION_ENDPOINT_NAME: Final[str] = "product-description"
PRODUCT_DESCRIPTION_HTTP_METHOD: Final[str] = "POST"


# ---------------------------------------------------------------------------
# Request contract
# ---------------------------------------------------------------------------

ProductDescriptionMode = Literal["generate", "improve"]

PRODUCT_DESCRIPTION_MODE_GENERATE: Final[ProductDescriptionMode] = "generate"
PRODUCT_DESCRIPTION_MODE_IMPROVE: Final[ProductDescriptionMode] = "improve"
PRODUCT_DESCRIPTION_MODES: Final[tuple[ProductDescriptionMode, ...]] = (
    PRODUCT_DESCRIPTION_MODE_GENERATE,
    PRODUCT_DESCRIPTION_MODE_IMPROVE,
)


class ProductDescriptionRequest(TypedDict):
    """JSON request body accepted by the product-description endpoint.

    Required fields:
    - ``mode``
    - ``product_name``
    - ``category_id``
    - ``price``

    Conditional/optional fields:
    - ``current_description`` is required by validation when mode is improve.
    - The client does not send a language. The backend detects ``ar`` or ``en``
      from the product name, current description, and additional information.
    - ``additional_information`` is temporary user/AI context used only to
      regenerate the description. It is not stored separately.
    """

    mode: ProductDescriptionMode
    product_name: str
    category_id: int
    price: float
    current_description: NotRequired[str]
    additional_information: NotRequired[str]


PRODUCT_DESCRIPTION_REQUEST_EXAMPLE: Final[ProductDescriptionRequest] = {
    "mode": "improve",
    "product_name": "Smart Watch",
    "category_id": 12,
    "price": 80.0,
    "current_description": "Good watch.",
    "additional_information": (
        "Battery lasts up to five days and the watch is suitable for daily use."
    ),
}


# ---------------------------------------------------------------------------
# Success response contract
# ---------------------------------------------------------------------------


class ProductDescriptionResponse(TypedDict):
    """Successful JSON response returned for review by the Store Owner."""

    product_understanding: str
    generated_description: str
    improvement_summary: str
    suggested_information: str
    saved: Literal[False]


PRODUCT_DESCRIPTION_RESPONSE_EXAMPLE: Final[ProductDescriptionResponse] = {
    "product_understanding": (
        "A practical smart watch for customers who want essential daily features "
        "at an accessible price."
    ),
    "generated_description": (
        "Stay connected throughout your day with a practical smart watch designed "
        "for simple, comfortable everyday use. It brings essential activity and "
        "notification features together in one accessible device, making it a "
        "helpful choice for work, exercise, and daily routines."
    ),
    "improvement_summary": (
        "The description was changed from a generic statement into clear customer "
        "benefits while avoiding unsupported technical claims."
    ),
    "suggested_information": (
        "Add confirmed details about battery life, screen size, supported health "
        "features, compatibility, materials, and warranty to make the next version "
        "more specific and persuasive."
    ),
    "saved": False,
}


# ---------------------------------------------------------------------------
# Error response contract
# ---------------------------------------------------------------------------

ProductDescriptionErrorCode = Literal[
    "invalid_product_data",
    "store_access_denied",
    "category_not_found",
    "ai_service_unavailable",
    "invalid_ai_response",
]


class ProductDescriptionErrorResponse(TypedDict):
    """Stable error shape used by validation, access, and AI failures."""

    detail: str
    error_code: ProductDescriptionErrorCode


# ---------------------------------------------------------------------------
# Contract-level behavioral rules
# ---------------------------------------------------------------------------

PRODUCT_DESCRIPTION_CONTRACT_RULES: Final[tuple[str, ...]] = (
    "The endpoint returns an AI suggestion only and never saves a product.",
    "The generated description must be realistic, persuasive, and benefit-focused.",
    "The AI must not invent product specifications that were not provided.",
    "current_description is required when mode is improve.",
    "The backend detects ar or en from submitted product text; the client cannot select it.",
    "additional_information is temporary and is merged into the generated text only.",
    "suggested_information remains editable by the user before a later merge request.",
    "The success response must always return saved as false.",
)


__all__ = [
    "PRODUCT_DESCRIPTION_CONTRACT_RULES",
    "PRODUCT_DESCRIPTION_ENDPOINT_NAME",
    "PRODUCT_DESCRIPTION_ENDPOINT_PATH",
    "PRODUCT_DESCRIPTION_HTTP_METHOD",
    "PRODUCT_DESCRIPTION_MODE_GENERATE",
    "PRODUCT_DESCRIPTION_MODE_IMPROVE",
    "PRODUCT_DESCRIPTION_MODES",
    "PRODUCT_DESCRIPTION_REQUEST_EXAMPLE",
    "PRODUCT_DESCRIPTION_RESPONSE_EXAMPLE",
    "ProductDescriptionErrorCode",
    "ProductDescriptionErrorResponse",
    "ProductDescriptionMode",
    "ProductDescriptionRequest",
    "ProductDescriptionResponse",
]
