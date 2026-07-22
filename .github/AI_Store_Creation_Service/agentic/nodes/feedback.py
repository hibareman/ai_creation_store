"""Deterministic Feedback node."""

from __future__ import annotations

from typing import Any

from ...constants import WORKFLOW_STATUS_PROCESSING
from ..feedback import build_feedback
from ..state import AIStoreAgentState


def feedback_node(state: AIStoreAgentState) -> dict[str, Any]:
    return {
        "current_step": "feedback",
        "status": WORKFLOW_STATUS_PROCESSING,
        "feedback": build_feedback(state),
    }


__all__ = ["feedback_node"]
