"""
AI Store Creation API contract serializers.

These serializers define request/response shapes only.
They intentionally do not include business logic, DB access, or workflow orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping

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


class AIPersonalizationProgressSerializer(serializers.Serializer):
    resolved_core_count = serializers.IntegerField(min_value=0)
    total_core_count = serializers.IntegerField(min_value=1)
    core_complete = serializers.BooleanField()
    missing_core_keys = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )


class AIAgenticStoreSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)


class AIAgenticStoreSettingsSerializer(serializers.Serializer):
    currency = serializers.CharField(required=False)
    language = serializers.CharField(required=False)
    timezone = serializers.CharField(required=False)


class AIAgenticThemeSerializer(serializers.Serializer):
    theme_template = serializers.CharField(required=False)
    primary_color = serializers.CharField(required=False)
    secondary_color = serializers.CharField(required=False)
    font_family = serializers.CharField(required=False)
    logo_url = serializers.CharField(required=False, allow_blank=True)
    banner_url = serializers.CharField(required=False, allow_blank=True)


class AIAgenticCategorySerializer(serializers.Serializer):
    name = serializers.CharField()


class AIAgenticProductSerializer(serializers.Serializer):
    name = serializers.CharField()
    description = serializers.CharField()
    price = serializers.DecimalField(max_digits=12, decimal_places=2, coerce_to_string=False)
    sku = serializers.CharField()
    category_name = serializers.CharField()
    stock_quantity = serializers.IntegerField(min_value=0)
    image_url = serializers.CharField(required=False, allow_blank=True)


class AIAgenticClarificationQuestionSerializer(serializers.Serializer):
    question_key = serializers.CharField()
    question_text = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    other_option = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)
    recommendation = serializers.CharField(required=False, allow_blank=True)


class AIAgenticDraftPayloadDocumentationSerializer(serializers.Serializer):
    store = AIAgenticStoreSerializer(required=False)
    store_settings = AIAgenticStoreSettingsSerializer(required=False)
    theme = AIAgenticThemeSerializer(required=False)
    categories = AIAgenticCategorySerializer(many=True, required=False)
    products = AIAgenticProductSerializer(many=True, required=False)
    ai_analysis = serializers.CharField(
        required=False,
        help_text=(
            "Display-only AI explanation of how the current draft matches the user's "
            "store idea. It is updated after successful full or partial regeneration "
            "and is not persisted by Apply."
        ),
    )
    clarification_needed = serializers.BooleanField(required=False)
    clarification_questions = AIAgenticClarificationQuestionSerializer(many=True, required=False)
    error_code = serializers.CharField(required=False)
    user_message = serializers.CharField(required=False)
    retry_allowed = serializers.BooleanField(required=False)
    manual_edit_allowed = serializers.BooleanField(required=False)


class AIAgenticChangesDocumentationSerializer(serializers.Serializer):
    target_section = serializers.ChoiceField(choices=("theme", "categories", "products"))
    summary = serializers.CharField()
    details = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    analysis_updated = serializers.BooleanField()
    user_instruction = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AIAgenticDraftMetadataDocumentationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=tuple(sorted(AI_WORKFLOW_STATUSES)))
    current_step = serializers.CharField(required=False)
    mode = serializers.CharField(required=False)
    is_fallback = serializers.BooleanField(required=False)
    clarification_round_count = serializers.IntegerField(required=False, min_value=0)
    repair_attempt_count = serializers.IntegerField(required=False, min_value=0)
    max_clarification_rounds = serializers.IntegerField(required=False, min_value=0)
    max_repair_attempts = serializers.IntegerField(required=False, min_value=0)
    workflow_engine = serializers.CharField(required=False)
    personalization_progress = AIPersonalizationProgressSerializer(required=False)
    feedback = serializers.JSONField(required=False, allow_null=True)
    validation_errors = serializers.ListField(
        child=serializers.JSONField(), required=False, allow_empty=True
    )
    application_success = serializers.BooleanField(required=False)
    review_required = serializers.BooleanField(required=False)
    target_section = serializers.ChoiceField(
        choices=("theme", "categories", "products"), required=False
    )


class AIAgenticDraftStateDocumentationSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    draft_payload = AIAgenticDraftPayloadDocumentationSerializer()
    feedback = serializers.JSONField(required=False, allow_null=True)
    ai_changes = AIAgenticChangesDocumentationSerializer(required=False, allow_null=True)
    draft_metadata = AIAgenticDraftMetadataDocumentationSerializer()


class AIErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    error_code = serializers.CharField(required=False)


@extend_schema_field(
    {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "personalization_progress": {
                "type": "object",
                "required": [
                    "resolved_core_count", "total_core_count",
                    "core_complete", "missing_core_keys",
                ],
                "properties": {
                    "resolved_core_count": {"type": "integer", "minimum": 0},
                    "total_core_count": {"type": "integer", "enum": [10]},
                    "core_complete": {"type": "boolean"},
                    "missing_core_keys": {
                        "type": "array", "items": {"type": "string"},
                    },
                },
            }
        },
    }
)
class AIDraftMetadataField(serializers.JSONField):
    """Keep legacy metadata extensible while documenting safe Agentic progress."""


class AIDraftStateResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    draft_payload = serializers.JSONField()
    feedback = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Latest Feedback produced by the workflow, when available.",
    )
    ai_changes = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Description of the material changes made by the latest partial regeneration.",
    )
    draft_metadata = AIDraftMetadataField(
        help_text=(
            "Workflow metadata. Public status is one of: "
            f"{', '.join(sorted(AI_WORKFLOW_STATUSES))}."
        )
    )


class _ExactFieldsSerializerMixin:
    """Reject unknown input keys instead of silently ignoring them."""

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            expected_fields = set(self.fields)
            unexpected_fields = set(data) - expected_fields
            if unexpected_fields:
                raise serializers.ValidationError(
                    {
                        field_name: "Unexpected field."
                        for field_name in sorted(unexpected_fields)
                    }
                )
        return super().to_internal_value(data)


class AIAgenticClarificationAnswerSerializer(
    _ExactFieldsSerializerMixin,
    serializers.Serializer,
):
    question_key = serializers.CharField(
        trim_whitespace=True,
        allow_blank=False,
        help_text="Exact question_key returned by the current Agentic session.",
    )
    selected_option = serializers.CharField(
        trim_whitespace=True,
        allow_blank=False,
        help_text="One option returned for the matching question.",
    )
    custom_answer = serializers.CharField(
        required=False,
        trim_whitespace=True,
        allow_blank=False,
        min_length=2,
        max_length=300,
        help_text="Required when the selected option is Other or its localized equivalent.",
    )


class AIAgenticClarificationRequestSerializer(
    _ExactFieldsSerializerMixin,
    serializers.Serializer,
):
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
                        "custom_answer": {
                            "type": "string",
                            "minLength": 2,
                            "maxLength": 300,
                            "description": (
                                "Submit only when selected_option equals the "
                                "question's other_option value."
                            ),
                        },
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
    user_instruction = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=1000,
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
    status = serializers.CharField()
    current_step = serializers.CharField()
    mode = serializers.CharField()
    is_fallback = serializers.BooleanField()
    application_success = serializers.BooleanField()
    created_categories_count = serializers.IntegerField(min_value=0)
    created_products_count = serializers.IntegerField(min_value=0)
    completed_at = serializers.DateTimeField()
    clarification_round_count = serializers.IntegerField(required=False, min_value=0)
    repair_attempt_count = serializers.IntegerField(required=False, min_value=0)
    max_clarification_rounds = serializers.IntegerField(required=False, min_value=0)
    max_repair_attempts = serializers.IntegerField(required=False, min_value=0)
    workflow_engine = serializers.CharField(required=False)


class EmptySerializer(serializers.Serializer):
    pass


class AIGeneratedStoreResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    store = serializers.JSONField()
    settings = serializers.JSONField(allow_null=True)
    theme = serializers.JSONField(allow_null=True)
    categories_count = serializers.IntegerField(min_value=0)
    categories = serializers.ListField(child=serializers.JSONField())
    products_count = serializers.IntegerField(min_value=0)
    products = serializers.ListField(child=serializers.JSONField())
