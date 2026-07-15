"""AI-powered Clarify node for terminal-safe first-round questions."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
)
from ..clarifying import generate_clarification_questions
from ..state import AIStoreAgentState


def clarify_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        if state.get("description_sufficient") is not False:
            raise ValueError("Clarify requires insufficient semantic analysis.")
        questions = generate_clarification_questions(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            user_id=state.get("user_id"),
            normalized_description=state.get("normalized_description"),
            description_language=state.get("description_language"),
            detected_store_domains=state.get("detected_store_domains"),
            business_summary=state.get("business_summary"),
            target_audience=state.get("target_audience"),
            product_direction=state.get("product_direction"),
            blocking_missing_information=state.get("blocking_missing_information"),
            ambiguities=state.get("ambiguities"),
            clarification_round_count=state.get("clarification_round_count", 0),
            clarification_history=state.get("clarification_history", []),
            clarification_facts=state.get("clarification_facts", {}),
        )
        state_questions = deepcopy(questions)
        payload_questions = deepcopy(questions)
        update = {
            "current_step": "clarify",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "mode": "clarification",
            "route_decision": "human_review",
            "validation_errors": [],
            "clarification_questions": state_questions,
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": payload_questions,
            },
        }
        json.dumps(update, ensure_ascii=False, allow_nan=False)
        return update
    except Exception:
        return _safe_clarify_failure_update()


def _safe_clarify_failure_update() -> dict[str, Any]:
    return {
        "current_step": "clarify",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "validation_errors": [],
        "clarification_questions": [],
        "draft_payload": {},
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


__all__ = ["clarify_node"]
