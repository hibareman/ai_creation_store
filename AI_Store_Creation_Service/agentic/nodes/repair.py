"""Provider-backed Repair node for the agentic AI Store Creation graph."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..repairing import repair_draft_payload
from ..state import AIStoreAgentState

logger = logging.getLogger(__name__)

_FAILURE_ISSUE = {
    "path": "draft_payload",
    "code": "repair_internal_failure",
    "message": "Draft repair could not be completed safely.",
    "repairable": False,
}
_ISSUE_KEYS = {"path", "code", "message", "repairable"}


def repair_node(state: AIStoreAgentState) -> dict[str, Any]:
    current_count = _repair_count_for_invocation(state.get("repair_attempt_count"))
    if current_count is None:
        logger.error(
            "AGENTIC NODE FAILURE | node=repair | reason=invalid_or_exhausted_attempt_count "
            "| store_id=%s | tenant_id=%s | repair_attempt_count=%r",
            state.get("store_id"),
            state.get("tenant_id"),
            state.get("repair_attempt_count"),
        )
        return _safe_repair_failure_update(
            state,
            repair_attempt_count=_safe_repair_count(state.get("repair_attempt_count")),
        )

    next_attempt_count = current_count + 1
    try:
        repaired_candidate = repair_draft_payload(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            user_id=state.get("user_id"),
            normalized_description=state.get("normalized_description"),
            expected_mode=state.get("mode"),
            current_draft=state.get("draft_payload"),
            validation_errors=state.get("validation_errors"),
            available_theme_templates=state.get("available_theme_templates"),
            repair_attempt_count=current_count,
            blueprint=state.get("blueprint"),
            effective_personalization_context=state.get(
                "effective_personalization_context"
            ),
            locked_user_decisions=state.get("clarification_facts"),
            require_personalization_constraints=True,
        )
        update = {
            "current_step": "repair",
            "status": WORKFLOW_STATUS_PROCESSING,
            "route_decision": "validate",
            "repair_attempt_count": next_attempt_count,
            "draft_payload": deepcopy(repaired_candidate),
        }
        _assert_json_serializable(update)
        logger.warning(
            "AGENTIC NODE SUCCESS | node=repair | store_id=%s | tenant_id=%s "
            "| attempt=%s | previous_validation_errors=%s",
            state.get("store_id"),
            state.get("tenant_id"),
            next_attempt_count,
            json.dumps(state.get("validation_errors", []), ensure_ascii=False, default=str),
        )
        return update
    except Exception as exc:
        logger.exception(
            "AGENTIC NODE FAILURE | node=repair | store_id=%s | tenant_id=%s "
            "| attempt=%s | error_type=%s | error=%r | validation_errors=%s",
            state.get("store_id"),
            state.get("tenant_id"),
            next_attempt_count,
            type(exc).__name__,
            exc,
            json.dumps(state.get("validation_errors", []), ensure_ascii=False, default=str),
        )
        return _safe_repair_failure_update(
            state,
            repair_attempt_count=next_attempt_count,
        )


def _repair_count_for_invocation(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value >= MAX_REPAIR_ATTEMPTS:
        return None
    return value


def _safe_repair_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return min(value, MAX_REPAIR_ATTEMPTS)


def _safe_repair_failure_update(
    state: AIStoreAgentState,
    *,
    repair_attempt_count: int,
) -> dict[str, Any]:
    update = {
        "current_step": "repair",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "repair_attempt_count": min(
            _safe_repair_count(repair_attempt_count),
            MAX_REPAIR_ATTEMPTS,
        ),
        "draft_payload": _safe_draft_payload(state.get("draft_payload")),
        "validation_errors": _safe_validation_errors(state.get("validation_errors")),
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }
    _assert_json_serializable(update)
    return update


def _safe_draft_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        candidate = dict(deepcopy(value))
        _assert_json_serializable(candidate)
        return candidate
    except Exception:
        return {}


def _safe_validation_errors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return [dict(_FAILURE_ISSUE)]

    safe_errors: list[dict[str, Any]] = []
    try:
        for issue in value:
            if not isinstance(issue, Mapping):
                return [dict(_FAILURE_ISSUE)]
            issue_copy = dict(deepcopy(issue))
            if set(issue_copy) != _ISSUE_KEYS:
                return [dict(_FAILURE_ISSUE)]
            if not isinstance(issue_copy["path"], str) or not issue_copy["path"].strip():
                return [dict(_FAILURE_ISSUE)]
            if not isinstance(issue_copy["code"], str) or not issue_copy["code"].strip():
                return [dict(_FAILURE_ISSUE)]
            if not isinstance(issue_copy["message"], str) or not issue_copy["message"].strip():
                return [dict(_FAILURE_ISSUE)]
            if not isinstance(issue_copy["repairable"], bool):
                return [dict(_FAILURE_ISSUE)]
            _assert_json_serializable(issue_copy)
            safe_errors.append(issue_copy)
    except Exception:
        return [dict(_FAILURE_ISSUE)]

    return safe_errors or [dict(_FAILURE_ISSUE)]


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value)


__all__ = ["repair_node"]
