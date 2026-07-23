"""Validate generated drafts and route repairable failures through the repair loop."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_REPAIR_ATTEMPTS, RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE, WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState
from ..validation import validate_generated_draft

logger = logging.getLogger(__name__)


def validate_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        payload, detected_mode, errors = validate_generated_draft(
            draft_payload=state.get("draft_payload"),
            expected_mode=state.get("mode"),
            available_theme_templates=state.get("available_theme_templates"),
            blueprint=state.get("blueprint"),
            effective_personalization_context=state.get("effective_personalization_context"),
            require_personalization_context=False,
        )
    except Exception:
        logger.exception("Structural draft validation failed unexpectedly.")
        return _failed([], {}, state.get("repair_attempt_count"))

    if errors:
        attempts = _safe_count(state.get("repair_attempt_count"))
        logger.error(
            "AGENTIC VALIDATION RESULT | store_id=%s | tenant_id=%s "
            "| mode=%s | repair_attempt_count=%s | errors=%s",
            state.get("store_id"),
            state.get("tenant_id"),
            detected_mode,
            attempts,
            errors,
        )
        can_repair = attempts < MAX_REPAIR_ATTEMPTS and all(
            issue.get("repairable") is True for issue in errors
        )
        if can_repair:
            return {
                "current_step": "validate",
                "status": WORKFLOW_STATUS_PROCESSING,
                "mode": detected_mode or "draft_ready",
                "route_decision": "repair",
                "validation_errors": deepcopy(errors),
                "draft_payload": deepcopy(payload),
                "clarification_questions": [],
                "repair_attempt_count": attempts,
            }
        return _failed(errors, payload, attempts)

    logger.warning(
        "AGENTIC VALIDATION SUCCESS | store_id=%s | tenant_id=%s | mode=%s",
        state.get("store_id"),
        state.get("tenant_id"),
        detected_mode,
    )
    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_PROCESSING,
        "route_decision": "human_review",
        "validation_errors": [],
        "draft_payload": deepcopy(payload),
        "mode": detected_mode,
        "clarification_questions": [],
        "repair_attempt_count": _safe_count(state.get("repair_attempt_count")),
    }


def _safe_count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _failed(errors: list[dict[str, Any]], payload: dict[str, Any], attempts: Any) -> dict[str, Any]:
    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "validation_errors": deepcopy(errors),
        "repair_attempt_count": min(_safe_count(attempts), MAX_REPAIR_ATTEMPTS),
        "draft_payload": deepcopy(payload),
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }

__all__ = ["validate_node"]
