"""
AI Store Creation API contract serializers.

These serializers define request/response shapes only.
They intentionally do not include business logic, DB access, or workflow orchestration.
"""

from __future__ import annotations

from rest_framework import serializers


class AIStartDraftRequestSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)
    user_store_description = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class AIDraftStateResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    draft_payload = serializers.JSONField()
    draft_metadata = serializers.JSONField()


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
    final_status = serializers.CharField()
    store_core_applied = serializers.BooleanField()
    categories = AIApplyItemsResultSerializer()
    products = AIApplyItemsResultSerializer()
    draft_cleanup_scheduled = serializers.BooleanField()


class EmptySerializer(serializers.Serializer):
    pass
