"""Final deterministic persistence node for the Agentic Store workflow."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from ...apply_services import apply_current_ai_draft_to_store
from ..state import AIStoreAgentState


def apply_store_node(state: AIStoreAgentState) -> dict[str, Any]:
    if not state.get("review_approved"):
        return {
            "status": "failed_recoverable",
            "current_step": "recoverable_failure",
            "mode": "failed_recoverable",
            "route_decision": "failed_recoverable",
            "application_success": False,
            "error_code": "review_not_approved",
            "user_message": "The store draft must be approved before it can be applied.",
        }

    try:
        user = get_user_model().objects.get(pk=state["user_id"])
        result = apply_current_ai_draft_to_store(
            store_id=state["store_id"],
            user=user,
            tenant_id=state["tenant_id"],
        )
    except (get_user_model().DoesNotExist, ValidationError) as exc:
        return {
            "status": "failed_recoverable",
            "current_step": "recoverable_failure",
            "mode": "failed_recoverable",
            "route_decision": "failed_recoverable",
            "application_success": False,
            "error_code": "store_application_failed",
            "user_message": str(exc),
        }

    return {
        **result,
        "route_decision": "completed",
        "draft_payload": state.get("draft_payload", {}),
        "clarification_questions": [],
        "validation_errors": [],
    }


__all__ = ["apply_store_node"]
