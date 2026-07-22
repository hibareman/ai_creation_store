from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view

from .constants import (
    AGENTIC_CLARIFICATION_INVALID_ERROR_CODE,
    AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE,
    AGENTIC_OPERATION_NOT_AVAILABLE_ERROR_CODE,
    AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_APPLIED,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .serializers import (
    AIAgenticDraftStateDocumentationSerializer,
    AIApplyDraftResponseSerializer,
    AIErrorResponseSerializer,
    AIGeneratedStoreResponseSerializer,
    AIClarificationRequestSerializer,
    AIDraftStateResponseSerializer,
    AIRegenerateSectionRequestSerializer,
    AIStartDraftRequestSerializer,
    EmptySerializer,
)
from .generated_store_services import get_applied_ai_store_details
from .services import (
    apply_current_ai_draft_to_store,
    get_current_ai_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
    start_ai_draft_workflow,
)

AGENTIC_SWAGGER_TAG = "Agentic Updates"

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(response=AIErrorResponseSerializer, description="Invalid request or workflow state."),
    401: OpenApiResponse(response=AIErrorResponseSerializer, description="Authentication credentials were not provided or invalid."),
    403: OpenApiResponse(response=AIErrorResponseSerializer, description="The authenticated user cannot access this store."),
    404: OpenApiResponse(response=AIErrorResponseSerializer, description="Store or temporary AI draft was not found."),
}

READY_DRAFT_RESPONSE_EXAMPLE = {
    "store_id": 582,
    "draft_payload": {
        "store": {
            "name": "قهوة بيتك المختصة",
            "description": "متجر متخصص في القهوة المختصة وأدوات التحضير المنزلية في السعودية.",
        },
        "store_settings": {
            "currency": "SAR",
            "language": "ar",
            "timezone": "Asia/Riyadh",
        },
        "theme": {
            "theme_template": "Modern",
            "primary_color": "#4B2E2A",
            "secondary_color": "#D4AF37",
            "font_family": "Cairo",
            "logo_url": "",
            "banner_url": "",
        },
        "categories": [{"name": "حبوب القهوة المختصة"}],
        "products": [
            {
                "name": "حبوب كولومبية - تحميص متوسط",
                "description": "حبوب متوازنة مناسبة للتقطير اليدوي.",
                "price": 130,
                "sku": "CB-COL-001",
                "category_name": "حبوب القهوة المختصة",
                "stock_quantity": 40,
                "image_url": "",
            }
        ],
        "ai_analysis": "حلّل الذكاء الاصطناعي فكرة المتجر وربط السوق والفئات والمنتجات والهوية البصرية ضمن مسودة واحدة متناسقة.",
        "clarification_needed": False,
        "clarification_questions": [],
    },
    "draft_metadata": {
        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "current_step": "ready_for_review",
        "mode": "draft_ready",
        "is_fallback": False,
        "clarification_round_count": 0,
        "repair_attempt_count": 0,
        "max_clarification_rounds": 3,
        "max_repair_attempts": 3,
        "workflow_engine": "agentic",
        "personalization_progress": {
            "resolved_core_count": 10,
            "total_core_count": 10,
            "core_complete": True,
            "missing_core_keys": [],
        },
        "validation_errors": [],
        "application_success": False,
        "review_required": True,
    },
}


class AIBaseAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    _NOT_FOUND_MESSAGES = {
        "Store not found or access denied",
        "No temporary AI draft found for this store",
    }

    @staticmethod
    def _extract_validation_message(exc: DjangoValidationError) -> str:
        messages = getattr(exc, "messages", None)
        if isinstance(messages, list) and messages:
            return str(messages[0])

        message = str(exc)
        if message.startswith("['") and message.endswith("']"):
            return message[2:-2]
        return message

    def _validation_error_response(self, exc: DjangoValidationError) -> Response:
        message = self._extract_validation_message(exc)
        response_status = (
            status.HTTP_404_NOT_FOUND
            if message in self._NOT_FOUND_MESSAGES
            else status.HTTP_400_BAD_REQUEST
        )

        payload = {"detail": message}
        if message == AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE:
            payload["error_code"] = AGENTIC_CLARIFICATION_INVALID_ERROR_CODE
        elif message == AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE:
            payload["error_code"] = AGENTIC_OPERATION_NOT_AVAILABLE_ERROR_CODE

        return Response(payload, status=response_status)

    @staticmethod
    def _validated_response_payload(serializer_class, payload: dict) -> dict:
        serializer = serializer_class(data=payload)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


@extend_schema_view(
    post=extend_schema(
        summary="Start AI draft workflow",
        description=(
            "Create a draft store immediately and generate the initial temporary AI draft state. "
            "Request prefers user_description; deprecated user_store_description is accepted as a fallback. "
            "A name field is not required. Response includes store_id, draft_payload, and draft_metadata. "
            "Agentic sessions are selected internally by feature flag and return terminal statuses only: "
            "needs_clarification, ready_for_review, or failed_recoverable. Successful drafts include the display-only "
            "draft_payload.ai_analysis field used by the new frontend review experience."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        request=AIStartDraftRequestSerializer,
        examples=[
            OpenApiExample(
                name="Start Coffee Store",
                value={
                    "user_description": (
                        "أريد متجرًا سعوديًا لبيع حبوب القهوة المختصة وأدوات التحضير المنزلية "
                        "للمبتدئين، بأسعار متوسطة وهوية عربية حديثة."
                    )
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Agentic Ready For Review",
                value=READY_DRAFT_RESPONSE_EXAMPLE,
                response_only=True,
                status_codes=["201"],
            ),
            OpenApiExample(
                name="Agentic Needs Clarification",
                value={
                    "store_id": 10,
                    "draft_payload": {
                        "clarification_needed": True,
                        "clarification_questions": [
                            {
                                "question_key": "price_positioning",
                                "question_text": "How should prices be positioned?",
                                "options": ["Affordable", "Premium", "Other"],
                                "other_option": "Other",
                            }
                        ],
                    },
                    "draft_metadata": {
                        "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                        "mode": "clarification",
                        "workflow_engine": "agentic",
                        "clarification_round_count": 0,
                        "personalization_progress": {
                            "resolved_core_count": 6,
                            "total_core_count": 10,
                            "core_complete": False,
                            "missing_core_keys": [
                                "customer_problem",
                                "unique_value_proposition",
                                "brand_personality",
                                "visual_preferences",
                            ],
                        },
                    },
                },
                response_only=True,
            ),
            OpenApiExample(
                name="Recoverable Failure",
                value={
                    "store_id": 10,
                    "draft_payload": {
                        "clarification_needed": False,
                        "clarification_questions": [],
                        "error_code": "ai_generation_failed",
                        "user_message": (
                            "We could not complete AI generation right now. "
                            "You can retry or edit the draft manually."
                        ),
                        "retry_allowed": True,
                        "manual_edit_allowed": True,
                    },
                    "draft_metadata": {
                        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                        "mode": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                        "is_fallback": True,
                        "workflow_engine": "agentic",
                    },
                },
                response_only=True,
            ),
        ],
        responses={201: AIAgenticDraftStateDocumentationSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIStartDraftAPIView(AIBaseAPIView):
    serializer_class = AIStartDraftRequestSerializer

    def post(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)
        normalized_user_description = request_serializer.validated_data[
            "normalized_user_description"
        ]

        try:
            draft_state = start_ai_draft_workflow(
                user=request.user,
                tenant_id=tenant_id,
                user_store_description=normalized_user_description,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
        summary="Get current AI draft state",
        description=(
            "Return the latest temporary Agentic draft for the authenticated store owner. When the most recent "
            "operation was partial regeneration, the response may also contain top-level ai_changes. The complete "
            "explanation of the current draft is returned in draft_payload.ai_analysis."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        examples=[
            OpenApiExample(
                name="Current Ready Draft",
                value=READY_DRAFT_RESPONSE_EXAMPLE,
                response_only=True,
                status_codes=["200"],
            )
        ],
        responses={200: AIAgenticDraftStateDocumentationSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AICurrentDraftAPIView(AIBaseAPIView):
    serializer_class = EmptySerializer

    def get(self, request, store_id: int, *args, **kwargs):
        tenant_id = getattr(request, "tenant_id", None)

        try:
            draft_state = get_current_ai_draft(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Submit clarification round",
        description=(
            "Submit one clarification input through clarification_answers and advance the AI draft workflow. "
            "Agentic sessions require an exact non-empty MCQ answer list containing question_key and "
            "selected_option. Legacy sessions retain the older compatibility input contract that accepts "
            "a non-empty string, object, or list."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        request=AIClarificationRequestSerializer,
        examples=[
            OpenApiExample(
                name="Agentic Normal Answer",
                value={
                    "clarification_answers": [
                        {
                            "question_key": "price_positioning",
                            "selected_option": "Premium",
                        }
                    ]
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Agentic Other Answer",
                value={
                    "clarification_answers": [
                        {
                            "question_key": "product_offering",
                            "selected_option": "Other",
                            "custom_answer": "Handmade natural soaps",
                        }
                    ]
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Agentic Ready After Clarification",
                value={
                    "store_id": 10,
                    "draft_payload": {"clarification_needed": False, "clarification_questions": []},
                    "draft_metadata": {
                        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                        "mode": "draft_ready",
                        "workflow_engine": "agentic",
                        "clarification_round_count": 1,
                        "personalization_progress": {
                            "resolved_core_count": 10,
                            "total_core_count": 10,
                            "core_complete": True,
                            "missing_core_keys": [],
                        },
                    },
                },
                response_only=True,
            ),
            OpenApiExample(
                name="Invalid Agentic Answers",
                value={
                    "detail": AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE,
                    "error_code": AGENTIC_CLARIFICATION_INVALID_ERROR_CODE,
                },
                response_only=True,
                status_codes=["400"],
            ),
        ],
        responses={200: AIAgenticDraftStateDocumentationSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIClarificationAPIView(AIBaseAPIView):
    serializer_class = AIClarificationRequestSerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)
        clarification_answers = request_serializer.validated_data["clarification_answers"]

        try:
            process_clarification_round(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
                clarification_answers=clarification_answers,
            )
            draft_state = get_current_ai_draft(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Regenerate full AI draft",
        description=(
            "Generate a complete alternative draft for the same store and Agentic session using the saved "
            "original description, clarification context, and confirmed personalization. The endpoint accepts "
            "an empty JSON object only. On success, the complete draft and draft_payload.ai_analysis are replaced "
            "atomically and the workflow remains ready_for_review."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        request=EmptySerializer,
        examples=[
            OpenApiExample(name="Empty Request", value={}, request_only=True),
            OpenApiExample(
                name="Full Regeneration Result",
                value=READY_DRAFT_RESPONSE_EXAMPLE,
                response_only=True,
                status_codes=["200"],
            ),
        ],
        responses={200: AIAgenticDraftStateDocumentationSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIRegenerateDraftAPIView(AIBaseAPIView):
    serializer_class = EmptySerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)

        try:
            draft_state = regenerate_store_draft(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Regenerate AI draft section",
        description=(
            "Regenerate exactly one supported part of a ready_for_review Agentic draft. For theme, only theme and "
            "ai_analysis change. For products, only products and ai_analysis change while existing categories are "
            "preserved. For categories, categories and products are regenerated together to preserve category_name "
            "integrity, and ai_analysis is updated. The merge is atomic: the old draft remains unchanged on failure. "
            "The response returns top-level ai_changes with target_section, summary, details, analysis_updated, and "
            "the optional user_instruction."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        request=AIRegenerateSectionRequestSerializer,
        examples=[
            OpenApiExample(
                name="Regenerate Theme",
                value={
                    "target_section": "theme",
                    "user_instruction": (
                        "غيّر الثيم ليكون أكثر فخامة وحداثة مع ألوان مختلفة بوضوح، "
                        "مع الحفاظ على هوية متجر القهوة."
                    ),
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Regenerate Products",
                value={
                    "target_section": "products",
                    "user_instruction": (
                        "أنشئ منتجات جديدة ومتنوعة فعليًا ضمن مجال القهوة المختصة، "
                        "مع الحفاظ على الفئات الحالية وSKU فريد لكل منتج."
                    ),
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Regenerate Categories",
                value={
                    "target_section": "categories",
                    "user_instruction": (
                        "أنشئ فئات بديلة أكثر تنظيمًا، ثم أعد توليد المنتجات لتتوافق "
                        "مع الفئات الجديدة بشكل كامل."
                    ),
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Theme Regeneration Response",
                value={
                    **READY_DRAFT_RESPONSE_EXAMPLE,
                    "ai_changes": {
                        "target_section": "theme",
                        "summary": "تم تحديث الهوية البصرية مع الحفاظ على بقية بيانات المسودة.",
                        "details": [
                            "تم تغيير قالب الثيم من Minimal إلى Modern.",
                            "تم تغيير اللونين الأساسي والثانوي.",
                            "تم تحديث تحليل الذكاء الاصطناعي ليتوافق مع الثيم الجديد.",
                        ],
                        "analysis_updated": True,
                        "user_instruction": "غيّر الثيم ليكون أكثر فخامة وحداثة.",
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        responses={200: AIAgenticDraftStateDocumentationSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIRegenerateSectionAPIView(AIBaseAPIView):
    serializer_class = AIRegenerateSectionRequestSerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)
        target_section = request_serializer.validated_data["target_section"]
        user_instruction = request_serializer.validated_data.get("user_instruction")

        try:
            regenerate_store_draft_section(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
                target_section=target_section,
                user_instruction=user_instruction,
            )
            draft_state = get_current_ai_draft(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_200_OK)


@extend_schema_view(
    post=extend_schema(
        summary="Apply current AI draft",
        description=(
            "Persist the current ready_for_review Agentic draft to store configuration, categories, and products "
            "inside the existing transactional Apply flow. draft_payload.ai_analysis and top-level ai_changes are "
            "display-only fields and are not persisted to application models. Temporary draft cleanup is scheduled "
            "only after a successful database commit."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        request=EmptySerializer,
        examples=[
            OpenApiExample(
                name="Apply Draft Success",
                value={
                    "store_id": 10,
                    "status": "completed",
                    "current_step": "completed",
                    "mode": "completed",
                    "is_fallback": False,
                    "application_success": True,
                    "created_categories_count": 1,
                    "created_products_count": 2,
                    "completed_at": "2026-07-19T12:00:00Z",
                },
                response_only=True,
            ),
        ],
        responses={200: AIApplyDraftResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIApplyDraftAPIView(AIBaseAPIView):
    serializer_class = EmptySerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)

        try:
            apply_result = apply_current_ai_draft_to_store(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIApplyDraftResponseSerializer,
            apply_result,
        )
        return Response(response_payload, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        summary="Get complete applied AI store",
        description=(
            "Return the persisted store, settings, theme, categories, products, inventory, and product images "
            "after Apply succeeds. ai_analysis and ai_changes are intentionally absent because they are temporary "
            "review-only fields and are not stored in application models."
        ),
        tags=[AGENTIC_SWAGGER_TAG],
        responses={200: AIGeneratedStoreResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIGeneratedStoreAPIView(AIBaseAPIView):
    serializer_class = EmptySerializer

    def get(self, request, store_id: int, *args, **kwargs):
        tenant_id = getattr(request, "tenant_id", None)
        try:
            payload = get_applied_ai_store_details(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIGeneratedStoreResponseSerializer,
            payload,
        )
        return Response(response_payload, status=status.HTTP_200_OK)
