"""
AI Store Creation API contract serializers.

These serializers define request/response shapes only.
They intentionally do not include business logic, DB access, or workflow orchestration.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .constants import AI_WORKFLOW_STATUSES
from .validators import validate_initial_description


class AIStartDraftRequestSerializer(serializers.Serializer):
    user_description = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )
    user_store_description = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        preferred = attrs.get("user_description")
        deprecated = attrs.get("user_store_description")

        if isinstance(preferred, str) and preferred.strip():
            description_candidate = preferred
        else:
            description_candidate = deprecated

        try:
            normalized_user_description = validate_initial_description(
                description_candidate if description_candidate is not None else ""
            )
        except DjangoValidationError as exc:
            messages = getattr(exc, "messages", None)
            message = str(messages[0]) if messages else str(exc)
            raise serializers.ValidationError(message) from exc

        attrs["normalized_user_description"] = normalized_user_description
        return attrs


class AIDraftStateResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    draft_payload = serializers.JSONField()
    draft_metadata = serializers.JSONField(
        help_text=(
            "Workflow metadata. Public status is one of: "
            f"{', '.join(sorted(AI_WORKFLOW_STATUSES))}."
        )
    )


class AIAgenticClarificationAnswerSerializer(serializers.Serializer):
    question_key = serializers.CharField(trim_whitespace=True, allow_blank=False)
    selected_option = serializers.CharField(trim_whitespace=True, allow_blank=False)


class AIAgenticClarificationRequestSerializer(serializers.Serializer):
    clarification_answers = AIAgenticClarificationAnswerSerializer(
        many=True,
        allow_empty=False,
    )


@extend_schema_field(
    {
        "oneOf": [
            {"type": "string"},
            {"type": "object"},
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["question_key", "selected_option"],
                    "additionalProperties": False,
                    "properties": {
                        "question_key": {"type": "string"},
                        "selected_option": {"type": "string"},
                    },
                },
            },
        ],
        "description": (
            "Legacy sessions accept a non-empty string, object, or list. "
            "Agentic sessions require a non-empty MCQ answer list with question_key "
            "and selected_option."
        ),
    }
)
class ClarificationAnswersField(serializers.Field):
    """
    Accept either:
    - non-empty string
    - non-empty object (dict)
    - non-empty list
    Reject null/blank/empty values and unsupported types.
    """

    default_error_messages = {
        "required": "clarification_answers is required.",
        "invalid": "clarification_answers must be a non-empty string, object, or list.",
        "blank": "clarification_answers must not be blank.",
        "empty_object": "clarification_answers object must not be empty.",
        "empty_list": "clarification_answers list must not be empty.",
    }

    def to_internal_value(self, data):
        if data is None:
            self.fail("required")

        if isinstance(data, str):
            value = data.strip()
            if not value:
                self.fail("blank")
            return value

        if isinstance(data, dict):
            if not data:
                self.fail("empty_object")
            return data

        if isinstance(data, list):
            if not data:
                self.fail("empty_list")
            return data

        self.fail("invalid")

    def to_representation(self, value):
        return value


class AIClarificationRequestSerializer(serializers.Serializer):
    clarification_answers = ClarificationAnswersField(required=True)


class AIRegenerateSectionRequestSerializer(serializers.Serializer):
    target_section = serializers.ChoiceField(
        choices=("theme", "categories", "products"),
        required=True,
    )


class AIApplyItemsResultSerializer(serializers.Serializer):
    created = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )
    skipped = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("This field must be an object.")

        expected_keys = {"created", "skipped"}
        if set(data.keys()) != expected_keys:
            raise serializers.ValidationError(
                "This field must contain exactly 'created' and 'skipped'."
            )

        return super().to_internal_value(data)


class AIApplyDraftResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    workflow_status = serializers.CharField()
    store_status = serializers.CharField()
    store_core_applied = serializers.BooleanField()
    categories = AIApplyItemsResultSerializer()
    products = AIApplyItemsResultSerializer()
    draft_cleanup_scheduled = serializers.BooleanField()


class EmptySerializer(serializers.Serializer):
    pass
