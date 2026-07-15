"""Session orchestration for cached agentic AI Store Creation workflows."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .agentic.runner import (
    build_safe_agentic_failure_state,
    resume_agentic_workflow,
    run_agentic_workflow,
    validate_agentic_terminal_state,
)
from .agentic_state_store import (
    delete_agentic_workflow_state,
    get_agentic_workflow_state,
    save_agentic_workflow_state,
)
from .audit_services import _write_ai_audit_log
from .constants import (
    MAX_CLARIFICATION_ROUNDS,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)


def start_cached_agentic_workflow(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    user_store_description: Any,
    normalized_description: Any,
    available_theme_templates: list[str] | None = None,
) -> dict[str, Any]:
    try:
        result = run_agentic_workflow(
            store_id=store_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_store_description=user_store_description,
            normalized_description=normalized_description,
            available_theme_templates=available_theme_templates,
        )
        terminal_state = validate_agentic_terminal_state(result)
        save_agentic_workflow_state(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            state=terminal_state,
        )
        _audit_terminal(
            action="agentic_session_start",
            status="completed",
            state=terminal_state,
        )
        return _json_defensive_copy(terminal_state)
    except Exception:
        failure = build_safe_agentic_failure_state(
            store_id=store_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_store_description=user_store_description,
            normalized_description=normalized_description,
        )
        _audit_failure(
            action="agentic_session_start",
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
        )
        return _json_defensive_copy(failure)


def resume_cached_agentic_workflow(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    clarification_answers: Any,
) -> dict[str, Any]:
    prior_state = get_cached_agentic_workflow(
        store_id=store_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if prior_state is None or not _is_resumable_clarification_state(prior_state):
        return _resume_failure(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            prior_state=prior_state,
        )

    prior_count = prior_state["clarification_round_count"]
    try:
        result = resume_agentic_workflow(
            prior_state=prior_state,
            clarification_answers=clarification_answers,
        )
        terminal_state = validate_agentic_terminal_state(result)
    except Exception:
        return _resume_failure(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            prior_state=prior_state,
        )

    transition = _classify_resume_transition(
        prior_count=prior_count,
        result_state=terminal_state,
    )
    if transition == "malformed":
        return _resume_failure(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            prior_state=prior_state,
        )

    if transition == "do_not_overwrite":
        _audit_terminal(
            action="agentic_session_resume",
            status="failed",
            state=terminal_state,
        )
        return _json_defensive_copy(terminal_state)

    try:
        save_agentic_workflow_state(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            state=terminal_state,
        )
    except Exception:
        return _resume_failure(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
            prior_state=prior_state,
        )

    _audit_terminal(
        action="agentic_session_resume",
        status=(
            "failed"
            if terminal_state["status"] == WORKFLOW_STATUS_FAILED_RECOVERABLE
            else "completed"
        ),
        state=terminal_state,
    )
    return _json_defensive_copy(terminal_state)


def get_cached_agentic_workflow(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
) -> dict[str, Any] | None:
    try:
        state = get_agentic_workflow_state(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=user_id,
        )
        if state is None:
            return None
        return validate_agentic_terminal_state(state)
    except Exception:
        return None


def delete_cached_agentic_workflow(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
) -> bool:
    deleted = delete_agentic_workflow_state(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user_id,
    )
    _write_ai_audit_log(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_id=user_id,
        action="agentic_session_delete",
        status="completed" if deleted else "failed",
        message="Agentic session delete requested.",
    )
    return deleted


def _is_resumable_clarification_state(state: dict[str, Any]) -> bool:
    return (
        state.get("status") == WORKFLOW_STATUS_NEEDS_CLARIFICATION
        and state.get("mode") == "clarification"
        and state.get("current_step") == "human_review"
        and state.get("route_decision") == "human_review"
        and state.get("validation_errors") == []
        and isinstance(state.get("clarification_questions"), list)
        and bool(state.get("clarification_questions"))
    )


def _classify_resume_transition(
    *,
    prior_count: Any,
    result_state: dict[str, Any],
) -> str:
    result_count = result_state.get("clarification_round_count")
    if not _is_valid_count(prior_count) or not _is_valid_count(result_count):
        return "malformed"
    if result_count < prior_count:
        return "malformed"
    if result_count > prior_count + 1:
        return "malformed"
    if result_count > MAX_CLARIFICATION_ROUNDS:
        return "malformed"

    result_status = result_state.get("status")
    if result_status in {
        WORKFLOW_STATUS_NEEDS_CLARIFICATION,
        WORKFLOW_STATUS_READY_FOR_REVIEW,
    }:
        return "overwrite" if result_count == prior_count + 1 else "malformed"
    if result_status == WORKFLOW_STATUS_FAILED_RECOVERABLE:
        if result_count == prior_count + 1:
            return "overwrite"
        if result_count == prior_count:
            return "do_not_overwrite"
        return "malformed"
    return "malformed"


def _is_valid_count(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_CLARIFICATION_ROUNDS
    )


def _resume_failure(
    *,
    tenant_id: Any,
    store_id: Any,
    user_id: Any,
    prior_state: dict[str, Any] | None,
) -> dict[str, Any]:
    failure = build_safe_agentic_failure_state(
        store_id=store_id,
        tenant_id=tenant_id,
        user_id=user_id,
        user_store_description=(
            prior_state.get("user_store_description", "") if prior_state else ""
        ),
        normalized_description=(
            prior_state.get("normalized_description", "") if prior_state else ""
        ),
        clarification_round_count=(
            prior_state.get("clarification_round_count", 0) if prior_state else 0
        ),
        repair_attempt_count=(
            prior_state.get("repair_attempt_count", 0) if prior_state else 0
        ),
    )
    _audit_failure(
        action="agentic_session_resume",
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=user_id,
    )
    return _json_defensive_copy(failure)


def _audit_terminal(*, action: str, status: str, state: dict[str, Any]) -> None:
    _write_ai_audit_log(
        tenant_id=state.get("tenant_id"),
        store_id=state.get("store_id"),
        actor_id=state.get("user_id"),
        action=action,
        status=status,
        message=(
            f"Terminal status={state.get('status')}; "
            f"step={state.get('current_step')}; "
            f"clarification_rounds={state.get('clarification_round_count', 0)}."
        ),
    )


def _audit_failure(
    *,
    action: str,
    tenant_id: Any,
    store_id: Any,
    user_id: Any,
) -> None:
    _write_ai_audit_log(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_id=user_id,
        action=action,
        status="failed",
        message="Agentic session operation failed safely.",
    )


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(deepcopy(value), ensure_ascii=False, allow_nan=False))


__all__ = [
    "delete_cached_agentic_workflow",
    "get_cached_agentic_workflow",
    "resume_cached_agentic_workflow",
    "start_cached_agentic_workflow",
]
