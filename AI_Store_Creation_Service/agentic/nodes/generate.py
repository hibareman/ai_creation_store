"""Generate a store draft after AI understanding is complete."""

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
from ..generation import generate_initial_draft_payload
from ..state import AIStoreAgentState

logger = logging.getLogger(__name__)


def generate_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        _validate_user_id(state.get("user_id"))
        context = state.get("effective_personalization_context")
        if not isinstance(context, dict):
            raise ValueError("Generation requires a personalization context object.")
        payload, mode = generate_initial_draft_payload(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            normalized_description=state.get("normalized_description"),
            available_theme_templates=state.get("available_theme_templates"),
            effective_personalization_context=context,
            blueprint=state.get("blueprint"),
            description_language=state.get("description_language"),
        )
        return {
            "current_step": "generate",
            "status": WORKFLOW_STATUS_PROCESSING,
            "draft_payload": deepcopy(payload),
            "mode": mode,
            "clarification_questions": [],
            "route_decision": "validate",
        }
    except Exception:
        logger.exception(
            "AI store draft generation failed | store_id=%s | tenant_id=%s",
            state.get("store_id"),
            state.get("tenant_id"),
        )
        return {
            "current_step": "generate",
            "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
            "mode": "failed_recoverable",
            "route_decision": "failed_recoverable",
            "draft_payload": {},
            "clarification_questions": [],
            "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
            "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
        }


def _validate_user_id(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Generation user id must be a positive integer.")


__all__ = ["generate_node"]