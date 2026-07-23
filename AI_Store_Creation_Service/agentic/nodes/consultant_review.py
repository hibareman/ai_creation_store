"""Evaluate a technically valid draft as an independent store consultant."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ...constants import (
    QUALITY_REVIEW_STATUS_NOT_STARTED,
    QUALITY_REVIEW_STATUS_PASSED,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..quality_contracts import (
    has_valid_quality_review_state,
    quality_state_defaults,
)
from ..quality_reviewing import review_generated_store_draft
from ..state import AIStoreAgentState

logger = logging.getLogger(__name__)


def consultant_review_node(state: AIStoreAgentState) -> dict[str, Any]:
    """Score the draft and record actionable issues without changing it."""

    try:
        _validate_review_preconditions(state)
        result = review_generated_store_draft(
            tenant_id=state.get("tenant_id"),
            store_id=state.get("store_id"),
            normalized_description=state.get("normalized_description"),
            clarification_facts=state.get("clarification_facts", {}),
            effective_personalization_context=state.get(
                "effective_personalization_context"
            ),
            blueprint=state.get("blueprint"),
            draft_payload=state.get("draft_payload"),
        )
    except Exception:
        logger.exception(
            "Agentic consultant review failed | store_id=%s | tenant_id=%s",
            state.get("store_id"),
            state.get("tenant_id"),
        )
        return _failed_result(quality_state_defaults())

    quality_status = result["quality_review_status"]
    logger.warning(
        "AGENTIC CONSULTANT REVIEW RESULT | store_id=%s | tenant_id=%s "
        "| quality_status=%s | score=%s | issues_count=%s",
        state.get("store_id"),
        state.get("tenant_id"),
        quality_status,
        result["quality_score"],
        len(result["quality_issues"]),
    )
    if quality_status == QUALITY_REVIEW_STATUS_PASSED:
        return {
            "current_step": "consultant_review",
            "status": WORKFLOW_STATUS_PROCESSING,
            "mode": "draft_ready",
            "route_decision": "human_review",
            "quality_review_status": quality_status,
            "quality_score": result["quality_score"],
            "quality_issues": deepcopy(result["quality_issues"]),
            "quality_revision_count": result["quality_revision_count"],
        }

    # Quality Improve is introduced in phase 3. Until then a weak draft fails
    # safely instead of reaching Human Review or structural Repair.
    return _failed_result(result)


def _validate_review_preconditions(state: AIStoreAgentState) -> None:
    for field_name in ("tenant_id", "store_id", "user_id"):
        value = state.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer.")
    if (
        state.get("status") != WORKFLOW_STATUS_PROCESSING
        or state.get("mode") != "draft_ready"
        or state.get("route_decision") != "consultant_review"
        or state.get("validation_errors") != []
    ):
        raise ValueError(
            "Consultant review requires a technically valid draft state."
        )
    if (
        not has_valid_quality_review_state(state)
        or state.get("quality_review_status")
        != QUALITY_REVIEW_STATUS_NOT_STARTED
    ):
        raise ValueError("Consultant review quality state is invalid.")
    for field_name in (
        "effective_personalization_context",
        "blueprint",
        "draft_payload",
    ):
        value = state.get(field_name)
        if not isinstance(value, Mapping) or not value:
            raise ValueError(f"{field_name} must be a non-empty object.")
    description = state.get("normalized_description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("normalized_description must be non-empty text.")
    clarification_facts = state.get("clarification_facts", {})
    if not isinstance(clarification_facts, Mapping):
        raise ValueError("clarification_facts must be an object.")


def _failed_result(quality_result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "current_step": "consultant_review",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "quality_review_status": quality_result["quality_review_status"],
        "quality_score": quality_result["quality_score"],
        "quality_issues": deepcopy(quality_result["quality_issues"]),
        "quality_revision_count": quality_result["quality_revision_count"],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


__all__ = ["consultant_review_node"]
