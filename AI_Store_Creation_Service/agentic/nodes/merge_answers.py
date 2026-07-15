"""Deterministic Merge Answers node for clarification resume."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_CLARIFICATION_ROUNDS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_PROCESSING,
)
from ..merging import merge_clarification_answers
from ..state import AIStoreAgentState


def merge_answers_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        _validate_resume_terminal_state(state)
        merged = merge_clarification_answers(
            clarification_questions=state.get("clarification_questions"),
            clarification_answers=state.get("clarification_answers"),
            clarification_history=state.get("clarification_history", []),
            clarification_facts=state.get("clarification_facts", {}),
            clarification_round_count=state.get("clarification_round_count"),
        )
        update: dict[str, Any] = {
            "current_step": "merge_answers",
            "status": WORKFLOW_STATUS_PROCESSING,
            "merge_valid": True,
            "clarification_round_count": merged["clarification_round_count"],
            "clarification_history": deepcopy(merged["clarification_history"]),
            "clarification_facts": deepcopy(merged["clarification_facts"]),
            "clarification_answers": [],
            "clarification_questions": [],
            "draft_payload": {},
            "validation_errors": [],
            "error_code": "",
            "user_message": "",
        }
        json.dumps(update, ensure_ascii=False, allow_nan=False)
        return update
    except Exception:
        return _safe_merge_failure_update(state)


def _validate_resume_terminal_state(state: AIStoreAgentState) -> None:
    if not isinstance(state, Mapping):
        raise ValueError("State must be a mapping.")
    if state.get("workflow_entry") != "clarification_resume":
        raise ValueError("Merge requires clarification_resume entry.")
    if state.get("status") != WORKFLOW_STATUS_NEEDS_CLARIFICATION:
        raise ValueError("Merge requires needs_clarification status.")
    if state.get("mode") != "clarification":
        raise ValueError("Merge requires clarification mode.")
    if state.get("current_step") != "human_review":
        raise ValueError("Merge requires human_review step.")
    if state.get("route_decision") != "human_review":
        raise ValueError("Merge requires human_review route.")
    if state.get("description_sufficient") is not False:
        raise ValueError("Merge requires insufficient prior analysis.")
    if state.get("validation_errors") != []:
        raise ValueError("Merge requires empty validation errors.")
    if not _is_positive_int(state.get("store_id")):
        raise ValueError("store_id is invalid.")
    if not _is_positive_int(state.get("tenant_id")):
        raise ValueError("tenant_id is invalid.")
    if not _is_positive_int(state.get("user_id")):
        raise ValueError("user_id is invalid.")
    if not isinstance(state.get("normalized_description"), str) or not state[
        "normalized_description"
    ].strip():
        raise ValueError("normalized_description is invalid.")
    draft_payload = state.get("draft_payload")
    if not isinstance(draft_payload, Mapping):
        raise ValueError("draft_payload is invalid.")
    if draft_payload.get("clarification_needed") is not True:
        raise ValueError("draft_payload must be clarification mode.")
    if draft_payload.get("clarification_questions") != state.get(
        "clarification_questions"
    ):
        raise ValueError("draft clarification questions must match state questions.")


def _safe_merge_failure_update(state: AIStoreAgentState) -> dict[str, Any]:
    return {
        "current_step": "merge_answers",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "merge_valid": False,
        "clarification_round_count": _safe_clarification_count(
            state.get("clarification_round_count")
            if isinstance(state, Mapping)
            else None
        ),
        "clarification_answers": [],
        "clarification_questions": [],
        "draft_payload": {},
        "validation_errors": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_clarification_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return min(value, MAX_CLARIFICATION_ROUNDS)


__all__ = ["merge_answers_node"]
