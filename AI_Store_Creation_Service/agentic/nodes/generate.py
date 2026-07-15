"""Provider-backed Generate node for the agentic AI Store Creation graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..generation import generate_initial_draft_payload
from ..state import AIStoreAgentState


def generate_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        _validate_user_id(state.get("user_id"))
        payload, mode = generate_initial_draft_payload(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            normalized_description=state.get("normalized_description"),
            available_theme_templates=state.get("available_theme_templates"),
        )
        clarification_questions = deepcopy(payload.get("clarification_questions", []))
        update: dict[str, Any] = {
            "current_step": "generate",
            "status": WORKFLOW_STATUS_PROCESSING,
            "draft_payload": payload,
            "mode": mode,
            "clarification_questions": clarification_questions,
            "route_decision": "validate",
        }
        if "validation_errors" in state:
            update["validation_errors"] = deepcopy(state["validation_errors"])
        return update
    except Exception:
        return _safe_generate_failure_update(state)


def _validate_user_id(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Generation user id must be a positive integer.")


def _safe_generate_failure_update(state: AIStoreAgentState) -> dict[str, Any]:
    update: dict[str, Any] = {
        "current_step": "generate",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "draft_payload": {},
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }
    if "validation_errors" in state:
        update["validation_errors"] = deepcopy(state["validation_errors"])
    return update


__all__ = ["generate_node"]
