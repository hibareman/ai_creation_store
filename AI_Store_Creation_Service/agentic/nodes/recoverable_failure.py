"""Placeholder Recoverable Failure node for the agentic graph."""

from __future__ import annotations

from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
)
from ..state import AIStoreAgentState


def _safe_text_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def recoverable_failure_node(state: AIStoreAgentState) -> dict[str, Any]:
    return {
        "current_step": "recoverable_failure",
        "mode": "failed_recoverable",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "route_decision": "failed_recoverable",
        "error_code": _safe_text_or_default(
            state.get("error_code"),
            RECOVERABLE_FAILURE_ERROR_CODE,
        ),
        "user_message": _safe_text_or_default(
            state.get("user_message"),
            RECOVERABLE_FAILURE_USER_MESSAGE,
        ),
    }


__all__ = ["recoverable_failure_node"]

