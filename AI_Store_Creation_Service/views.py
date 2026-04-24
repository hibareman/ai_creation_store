from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view

from .serializers import (
    AIApplyDraftResponseSerializer,
    AIClarificationRequestSerializer,
    AIDraftStateResponseSerializer,
    AIRegenerateSectionRequestSerializer,
    AIStartDraftRequestSerializer,
    EmptySerializer,
)
from .services import (
    apply_current_ai_draft_to_store,
    get_current_ai_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
    start_ai_draft_workflow,
)

DOC_ERROR_RESPONSES = {
    400: OpenApiResponse(description="Bad request"),
    403: OpenApiResponse(description="Permission denied"),
    404: OpenApiResponse(description="Not found"),
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
        return Response({"detail": message}, status=response_status)

    @staticmethod
    def _validated_response_payload(serializer_class, payload: dict) -> dict:
        serializer = serializer_class(data=payload)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


@extend_schema_view(
    post=extend_schema(
        summary="Start AI draft workflow",
        description="Create a draft store and generate the initial temporary AI draft state.",
        tags=["AI Store Creation"],
        request=AIStartDraftRequestSerializer,
        examples=[
            OpenApiExample(
                name="Start Draft Success",
                value={
                    "store_id": 10,
                    "draft_payload": {"clarification_needed": True, "clarification_questions": []},
                    "draft_metadata": {"status": "needs_clarification", "mode": "clarification"},
                },
                response_only=True,
            ),
        ],
        responses={201: AIDraftStateResponseSerializer, **DOC_ERROR_RESPONSES},
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
        description="Return current temporary draft payload and metadata for a store.",
        tags=["AI Store Creation"],
        responses={200: AIDraftStateResponseSerializer, **DOC_ERROR_RESPONSES},
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
        description="Submit one clarification input and advance the AI draft workflow to the next state.",
        tags=["AI Store Creation"],
        request=AIClarificationRequestSerializer,
        examples=[
            OpenApiExample(
                name="Clarification Success",
                value={
                    "store_id": 10,
                    "draft_payload": {"clarification_needed": False, "clarification_questions": []},
                    "draft_metadata": {"status": "draft_ready", "mode": "draft_ready"},
                },
                response_only=True,
            ),
        ],
        responses={200: AIDraftStateResponseSerializer, **DOC_ERROR_RESPONSES},
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
        description="Regenerate the full AI draft for the same store/session.",
        tags=["AI Store Creation"],
        request=EmptySerializer,
        responses={200: AIDraftStateResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIRegenerateDraftAPIView(AIBaseAPIView):
    serializer_class = EmptySerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)

        try:
            regenerate_store_draft(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
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
        summary="Regenerate AI draft section",
        description="Regenerate one section of the current AI draft payload.",
        tags=["AI Store Creation"],
        request=AIRegenerateSectionRequestSerializer,
        responses={200: AIDraftStateResponseSerializer, **DOC_ERROR_RESPONSES},
    ),
)
class AIRegenerateSectionAPIView(AIBaseAPIView):
    serializer_class = AIRegenerateSectionRequestSerializer

    def post(self, request, store_id: int, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)
        target_section = request_serializer.validated_data["target_section"]

        try:
            regenerate_store_draft_section(
                store_id=store_id,
                user=request.user,
                tenant_id=tenant_id,
                target_section=target_section,
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
        description="Apply the current AI draft to store configuration entities and schedule draft cleanup.",
        tags=["AI Store Creation"],
        request=EmptySerializer,
        examples=[
            OpenApiExample(
                name="Apply Draft Success",
                value={
                    "store_id": 10,
                    "final_status": "setup",
                    "store_core_applied": True,
                    "categories": {"created": ["Clothes"], "skipped": []},
                    "products": {"created": ["SKU-1"], "skipped": []},
                    "draft_cleanup_scheduled": True,
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
