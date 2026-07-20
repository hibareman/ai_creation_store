"""Placeholder Human Review node for the agentic AI Store Creation graph."""

from __future__ import annotations

from typing import Any

from ...constants import (
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from ..state import AIStoreAgentState


def human_review_node(state: AIStoreAgentState) -> dict[str, Any]:
    if (
        state.get("mode") == "clarification"
        or state.get("status") == WORKFLOW_STATUS_NEEDS_CLARIFICATION
    ):
        mode = "clarification"
        status = WORKFLOW_STATUS_NEEDS_CLARIFICATION
    else:
        mode = "draft_ready"
        status = WORKFLOW_STATUS_READY_FOR_REVIEW

    return {
        "current_step": "human_review" if mode == "clarification" else "ready_for_review",
        "mode": mode,
        "status": status,
        "route_decision": "human_review",
    }


__all__ = ["human_review_node"]

