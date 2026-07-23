"""Placeholder Recoverable Failure node for the agentic graph."""

from __future__ import annotations

import json
import logging
from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
)
from ..state import AIStoreAgentState

logger = logging.getLogger(__name__)


def _safe_text_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def recoverable_failure_node(state: AIStoreAgentState) -> dict[str, Any]:
    logger.error(
        "AGENTIC WORKFLOW RECOVERABLE FAILURE | store_id=%s | tenant_id=%s "
        "| failed_step=%s | error_code=%s | developer_message=%s "
        "| validation_errors=%s",
        state.get("store_id"),
        state.get("tenant_id"),
        state.get("current_step"),
        state.get("error_code"),
        state.get("developer_message"),
        json.dumps(state.get("validation_errors", []), ensure_ascii=False, default=str),
    )
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

