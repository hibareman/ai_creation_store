"""Deterministic Validate node for the agentic AI Store Creation graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState, ValidationIssue
from ..validation import validate_generated_draft


def validate_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        payload, detected_mode, validation_errors = validate_generated_draft(
            draft_payload=state.get("draft_payload"),
            expected_mode=state.get("mode"),
            available_theme_templates=state.get("available_theme_templates"),
        )
    except Exception:
        return _safe_failed_validation_update()

    if not validation_errors:
        return {
            "current_step": "validate",
            "status": WORKFLOW_STATUS_PROCESSING,
            "route_decision": "human_review",
            "validation_errors": [],
            "draft_payload": deepcopy(payload),
            "mode": detected_mode,
            "clarification_questions": deepcopy(
                payload.get("clarification_questions", [])
            ),
        }

    if _can_route_to_repair(validation_errors, state.get("repair_attempt_count", 0)):
        update = {
            "current_step": "validate",
            "status": WORKFLOW_STATUS_PROCESSING,
            "route_decision": "repair",
            "validation_errors": deepcopy(validation_errors),
            "draft_payload": deepcopy(payload),
        }
        if detected_mode in {"draft_ready", "clarification"}:
            update["mode"] = detected_mode
        return update

    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "validation_errors": deepcopy(validation_errors),
        "draft_payload": deepcopy(payload),
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


def _safe_failed_validation_update() -> dict[str, Any]:
    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "draft_payload": {},
        "clarification_questions": [],
        "validation_errors": [
            {
                "path": "draft_payload",
                "code": "validation_internal_failure",
                "message": "Draft validation could not be completed safely.",
                "repairable": False,
            }
        ],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


def _can_route_to_repair(issues: list[ValidationIssue], repair_attempt_count: Any) -> bool:
    if not issues or not all(issue.get("repairable") is True for issue in issues):
        return False
    if isinstance(repair_attempt_count, bool) or not isinstance(repair_attempt_count, int):
        return False
    return 0 <= repair_attempt_count < MAX_REPAIR_ATTEMPTS


__all__ = ["validate_node"]
