from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
    create_draft_store_for_ai_flow,
    generate_initial_store_draft,
    get_current_ai_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
)


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


class AIStartDraftAPIView(AIBaseAPIView):
    serializer_class = AIStartDraftRequestSerializer

    def post(self, request, *args, **kwargs):
        request_serializer = self.get_serializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        tenant_id = getattr(request, "tenant_id", None)
        name = request_serializer.validated_data["name"]
        user_store_description = request_serializer.validated_data["user_store_description"]

        try:
            store = create_draft_store_for_ai_flow(
                user=request.user,
                tenant_id=tenant_id,
                name=name,
                description="",
            )
            generate_initial_store_draft(
                store_id=store.id,
                user=request.user,
                tenant_id=tenant_id,
                user_store_description=user_store_description,
            )
            draft_state = get_current_ai_draft(
                store_id=store.id,
                user=request.user,
                tenant_id=tenant_id,
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        response_payload = self._validated_response_payload(
            AIDraftStateResponseSerializer,
            draft_state,
        )
        return Response(response_payload, status=status.HTTP_201_CREATED)


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
