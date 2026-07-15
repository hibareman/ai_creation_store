"""
AI Store Creation key naming strategy (foundation only).

This module defines Redis/cache key shapes for temporary AI draft storage.
No storage operations are implemented here.
"""

from django.conf import settings


# Key segments
AI_DRAFT_SCOPE = "store"
AI_DRAFT_MAIN_SUFFIX = "draft"
AI_DRAFT_META_SUFFIX = "meta"
AI_AGENTIC_SCOPE = "agentic"
AI_AGENTIC_STATE_SCHEMA_VERSION = 1
AI_AGENTIC_STATE_SUFFIX = "state"
AI_AGENTIC_STATE_MAX_BYTES = 512 * 1024

# Workflow limits
MAX_CLARIFICATION_ROUNDS = 3
MAX_REPAIR_ATTEMPTS = 3

# Workflow statuses
WORKFLOW_STATUS_PROCESSING = "processing"
WORKFLOW_STATUS_NEEDS_CLARIFICATION = "needs_clarification"
WORKFLOW_STATUS_READY_FOR_REVIEW = "ready_for_review"
WORKFLOW_STATUS_FAILED_RECOVERABLE = "failed_recoverable"
WORKFLOW_STATUS_APPLIED = "applied"

# Temporary backward-compatible legacy statuses accepted from older cached drafts.
LEGACY_WORKFLOW_STATUS_DRAFT_READY = "draft_ready"
LEGACY_WORKFLOW_STATUS_FAILED = "failed"

AI_WORKFLOW_STATUSES = {
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_APPLIED,
}

LEGACY_AI_WORKFLOW_STATUSES = {
    LEGACY_WORKFLOW_STATUS_DRAFT_READY,
    LEGACY_WORKFLOW_STATUS_FAILED,
}

READY_FOR_REVIEW_WORKFLOW_STATUSES = {
    WORKFLOW_STATUS_READY_FOR_REVIEW,
    LEGACY_WORKFLOW_STATUS_DRAFT_READY,
}

RECOVERABLE_FAILURE_ERROR_CODE = "ai_generation_failed"
RECOVERABLE_FAILURE_USER_MESSAGE = (
    "We could not complete AI generation right now. You can retry or edit the draft manually."
)

# Frontend-visible last-operation metadata.
LAST_OPERATION_PARTIAL_REGENERATION = "partial_regeneration"
LAST_OPERATION_STATUS_COMPLETED = "completed"
PARTIAL_REGENERATION_FAILED_ERROR_CODE = "partial_regeneration_failed"
PARTIAL_REGENERATION_FAILED_USER_MESSAGE = (
    "The selected section could not be regenerated. You can retry."
)

# Frontend-visible apply failure messages. Technical details stay in logs/audit.
CATEGORY_APPLY_FAILED_ERROR_CODE = "category_apply_failed"
CATEGORY_APPLY_FAILED_USER_MESSAGE = (
    "The draft categories could not be applied. Please retry."
)

PRODUCT_APPLY_FAILED_ERROR_CODE = "product_apply_failed"
PRODUCT_APPLY_FAILED_USER_MESSAGE = (
    "The draft products could not be applied. Please retry."
)

STORE_CORE_APPLY_FAILED_ERROR_CODE = "store_core_apply_failed"
STORE_CORE_APPLY_FAILED_USER_MESSAGE = (
    "The store configuration could not be applied. Please retry."
)

THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE = "theme_templates_unavailable"
THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE = (
    "Store generation is temporarily unavailable because no theme templates are configured. "
    "You can retry after templates become available."
)

AGENTIC_OPERATION_NOT_AVAILABLE_ERROR_CODE = "agentic_operation_not_available"
AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE = (
    "This operation is not available for the current AI session yet."
)

AGENTIC_CLARIFICATION_INVALID_ERROR_CODE = "invalid_clarification_answers"
AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE = (
    "The clarification answers are invalid or do not match the current questions."
)


def _normalize_store_id(store_id: int) -> int:
    """
    Validate and normalize store_id for key building.
    """
    normalized = int(store_id)
    if normalized <= 0:
        raise ValueError("store_id must be a positive integer")
    return normalized


def _validate_key_positive_int(value: int, *, field_name: str) -> int:
    """
    Strict positive integer validation for new scoped cache keys.

    Unlike the legacy draft key builder, this intentionally avoids silent
    coercion so tenant/store identity mismatches fail closed.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def build_ai_draft_key(store_id: int) -> str:
    """
    Main key for the full generated AI draft JSON.

    Pattern:
    <AI_DRAFT_PREFIX>:store:<store_id>:draft
    """
    sid = _normalize_store_id(store_id)
    return f"{settings.AI_DRAFT_PREFIX}:{AI_DRAFT_SCOPE}:{sid}:{AI_DRAFT_MAIN_SUFFIX}"


def build_ai_draft_meta_key(store_id: int) -> str:
    """
    Optional metadata key for lightweight workflow state (e.g. status, step).

    Pattern:
    <AI_DRAFT_PREFIX>:store:<store_id>:meta
    """
    sid = _normalize_store_id(store_id)
    return f"{settings.AI_DRAFT_PREFIX}:{AI_DRAFT_SCOPE}:{sid}:{AI_DRAFT_META_SUFFIX}"


def build_ai_agentic_state_key(
    *,
    tenant_id: int,
    store_id: int,
) -> str:
    """
    Tenant-scoped key for the cached agentic LangGraph session state.

    Pattern:
    <AI_DRAFT_PREFIX>:agentic:v1:tenant:<tenant_id>:store:<store_id>:state
    """
    tid = _validate_key_positive_int(tenant_id, field_name="tenant_id")
    sid = _validate_key_positive_int(store_id, field_name="store_id")
    return (
        f"{settings.AI_DRAFT_PREFIX}:{AI_AGENTIC_SCOPE}:"
        f"v{AI_AGENTIC_STATE_SCHEMA_VERSION}:tenant:{tid}:"
        f"store:{sid}:{AI_AGENTIC_STATE_SUFFIX}"
    )
