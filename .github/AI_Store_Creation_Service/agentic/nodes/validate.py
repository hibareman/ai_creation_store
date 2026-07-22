"""Structural validation node. No semantic/domain matching is performed."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState
from ..validation import validate_generated_draft

logger = logging.getLogger(__name__)


def validate_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        payload, detected_mode, validation_errors = validate_generated_draft(
            draft_payload=state.get("draft_payload"),
            expected_mode=state.get("mode"),
            available_theme_templates=state.get("available_theme_templates"),
            require_personalization_context=False,
        )
    except Exception:
        logger.exception("Structural draft validation failed unexpectedly.")
        return _failed([], {})

    if validation_errors:
        return _failed(validation_errors, payload)

    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_PROCESSING,
        "route_decision": "human_review",
        "validation_errors": [],
        "draft_payload": deepcopy(payload),
        "mode": detected_mode,
        "clarification_questions": [],
    }


def _failed(errors: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_step": "validate",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "validation_errors": deepcopy(errors),
        "draft_payload": deepcopy(payload),
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


__all__ = ["validate_node"]
