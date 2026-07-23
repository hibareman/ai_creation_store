"""API view for AI-assisted product-description suggestions.

The endpoint implemented by this module is registered in a later URL task:

    POST /api/ai/stores/{store_id}/products/description/

It supports generating a new description, improving an existing description,
and merging temporary additional information into a new suggestion. The view is
intentionally review-only: it never creates or updates a ``Product`` record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from users.permissions import TenantAuthenticated

from .product_description_contracts import (
    PRODUCT_DESCRIPTION_REQUEST_EXAMPLE,
    PRODUCT_DESCRIPTION_RESPONSE_EXAMPLE,
)
from .product_description_serializers import (
    ProductDescriptionErrorResponseSerializer,
    ProductDescriptionRequestSerializer,
    ProductDescriptionResponseSerializer,
)
from .product_description_services import (
    ProductDescriptionServiceError,
    generate_product_description_suggestion,
)


PRODUCT_DESCRIPTION_SWAGGER_TAG = "AI Product Description"

# Public service errors are deliberately mapped in the view rather than inside
# the service layer. This keeps HTTP concerns out of business logic while
# preserving one stable error body for the frontend.
_PRODUCT_DESCRIPTION_ERROR_STATUS = {
    "invalid_product_data": status.HTTP_400_BAD_REQUEST,
    "store_access_denied": status.HTTP_403_FORBIDDEN,
    "category_not_found": status.HTTP_404_NOT_FOUND,
    "ai_service_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "invalid_ai_response": status.HTTP_502_BAD_GATEWAY,
}

_PRODUCT_DESCRIPTION_ERROR_RESPONSES = {
    400: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="Required product data is missing or invalid.",
    ),
    401: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="Authentication credentials are missing or invalid.",
    ),
    403: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="The authenticated user cannot access the requested store.",
    ),
    404: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="The selected category was not found in the authorized store.",
    ),
    502: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="The AI provider returned an unusable response.",
    ),
    503: OpenApiResponse(
        response=ProductDescriptionErrorResponseSerializer,
        description="The AI provider is temporarily unavailable.",
    ),
}


def _first_serializer_error(errors: Any) -> str:
    """Extract a concise public message from DRF serializer errors.

    DRF errors may be nested dictionaries, lists, or ``ErrorDetail`` objects.
    The API contract requires a simple ``detail`` string, so this helper walks
    the first available branch without exposing internal implementation data.
    """

    if isinstance(errors, Mapping):
        for field_name, value in errors.items():
            message = _first_serializer_error(value)
            if message:
                if field_name == "non_field_errors":
                    return message
                return f"{field_name}: {message}"
        return "Invalid product data."

    if isinstance(errors, (list, tuple)):
        for value in errors:
            message = _first_serializer_error(value)
            if message:
                return message
        return "Invalid product data."

    message = str(errors).strip()
    return message or "Invalid product data."


def _validated_error_payload(*, detail: str, error_code: str) -> dict[str, Any]:
    """Validate internally constructed errors against the frozen API shape."""

    serializer = ProductDescriptionErrorResponseSerializer(
        data={"detail": detail, "error_code": error_code}
    )
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


@extend_schema_view(
    post=extend_schema(
        operation_id="ai_product_description_generate_or_improve",
        summary="Generate or improve a product description with AI",
        description=(
            "Generate a new product description or improve the current one for "
            "a tenant-owned store. The backend detects Arabic or English from "
            "the submitted product text, resolves the category inside the "
            "authorized store, and returns a review-only AI suggestion. Sending "
            "additional_information with mode=improve supports the merge-and-"
            "improve interaction. No Product or additional-information data is "
            "saved by this endpoint; saved is always false."
        ),
        tags=[PRODUCT_DESCRIPTION_SWAGGER_TAG],
        request=ProductDescriptionRequestSerializer,
        responses={
            200: ProductDescriptionResponseSerializer,
            **_PRODUCT_DESCRIPTION_ERROR_RESPONSES,
        },
        examples=[
            OpenApiExample(
                name="Generate English Description",
                value={
                    "mode": "generate",
                    "product_name": "Leather Bag",
                    "category_id": 4,
                    "price": 50,
                    "current_description": "",
                    "additional_information": "",
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Improve Arabic Description",
                value={
                    "mode": "improve",
                    "product_name": "ساعة ذكية",
                    "category_id": 7,
                    "price": 80,
                    "current_description": "ساعة جيدة للاستخدام اليومي.",
                    "additional_information": "",
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Merge Additional Information",
                value={
                    "mode": "improve",
                    "product_name": "حقيبة جلدية",
                    "category_id": 4,
                    "price": 50,
                    "current_description": "حقيبة عملية للاستخدام اليومي.",
                    "additional_information": (
                        "زاوية جاهزة للدمج: التركيز على سهولة الحمل. "
                        "المادة: جلد طبيعي؛ الأبعاد: 30 × 20 سم."
                    ),
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Successful Suggestion",
                value=PRODUCT_DESCRIPTION_RESPONSE_EXAMPLE,
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                name="Invalid Product Data",
                value={
                    "detail": "product_name: Product name is required.",
                    "error_code": "invalid_product_data",
                },
                response_only=True,
                status_codes=["400"],
            ),
            OpenApiExample(
                name="AI Temporarily Unavailable",
                value={
                    "detail": (
                        "The AI service is currently unavailable. Try again later "
                        "or write the description manually."
                    ),
                    "error_code": "ai_service_unavailable",
                },
                response_only=True,
                status_codes=["503"],
            ),
        ],
    )
)
class ProductDescriptionAPIView(GenericAPIView):
    """Return a validated AI suggestion without persisting product data."""

    permission_classes = [TenantAuthenticated]
    serializer_class = ProductDescriptionRequestSerializer

    def post(self, request, store_id: int, *args, **kwargs) -> Response:
        request_serializer = self.get_serializer(data=request.data)
        if not request_serializer.is_valid():
            payload = _validated_error_payload(
                detail=_first_serializer_error(request_serializer.errors),
                error_code="invalid_product_data",
            )
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = generate_product_description_suggestion(
                user=request.user,
                tenant_id=getattr(request, "tenant_id", None),
                store_id=store_id,
                validated_data=request_serializer.validated_data,
            )
        except ProductDescriptionServiceError as exc:
            response_status = _PRODUCT_DESCRIPTION_ERROR_STATUS.get(
                exc.error_code,
                status.HTTP_400_BAD_REQUEST,
            )
            payload = _validated_error_payload(
                detail=exc.detail,
                error_code=exc.error_code,
            )
            return Response(payload, status=response_status)

        # The service already validates provider output. Re-validating at the
        # transport boundary prevents an accidental future regression from
        # leaking a response that violates the public contract.
        response_serializer = ProductDescriptionResponseSerializer(data=result)
        if not response_serializer.is_valid():
            payload = _validated_error_payload(
                detail=(
                    "The AI service returned an unsuitable description. "
                    "Please try again."
                ),
                error_code="invalid_ai_response",
            )
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            dict(response_serializer.validated_data),
            status=status.HTTP_200_OK,
        )


__all__ = [
    "PRODUCT_DESCRIPTION_SWAGGER_TAG",
    "ProductDescriptionAPIView",
]
