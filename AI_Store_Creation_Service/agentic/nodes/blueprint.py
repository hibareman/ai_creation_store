"""Placeholder Blueprint node for the agentic AI Store Creation graph."""

from __future__ import annotations

from typing import Any

from ...constants import WORKFLOW_STATUS_PROCESSING
from ..state import AIStoreAgentState


def blueprint_node(state: AIStoreAgentState) -> dict[str, Any]:
    return {
        "current_step": "blueprint",
        "status": WORKFLOW_STATUS_PROCESSING,
        "route_decision": "generate",
    }


__all__ = ["blueprint_node"]

