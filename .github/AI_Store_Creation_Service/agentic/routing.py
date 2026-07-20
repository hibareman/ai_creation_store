"""Small deterministic routers for the simplified workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..constants import WORKFLOW_STATUS_PROCESSING
from .state import AIStoreAgentState

EntryRoute = Literal["understand", "merge_answers", "failed_recoverable"]
DecideRoute = Literal["clarify", "generate", "failed_recoverable"]
GenerateRoute = Literal["validate", "failed_recoverable"]
MergeRoute = Literal["understand", "failed_recoverable"]
ValidateRoute = Literal["human_review", "failed_recoverable"]


def _state_value(state: AIStoreAgentState, key: str) -> Any:
    return state.get(key) if isinstance(state, Mapping) else None


def route_workflow_entry(state: AIStoreAgentState) -> EntryRoute:
    entry = _state_value(state, "workflow_entry")
    if entry == "fresh":
        return "understand"
    if entry == "clarification_resume":
        return "merge_answers"
    return "failed_recoverable"


def route_after_merge(state: AIStoreAgentState) -> MergeRoute:
    if (
        _state_value(state, "merge_valid") is True
        and _state_value(state, "status") == WORKFLOW_STATUS_PROCESSING
    ):
        return "understand"
    return "failed_recoverable"


def route_after_decide(state: AIStoreAgentState) -> DecideRoute:
    decision = _state_value(state, "route_decision")
    if decision in {"clarify", "generate"}:
        return decision
    return "failed_recoverable"


def route_after_generate(state: AIStoreAgentState) -> GenerateRoute:
    return "validate" if _state_value(state, "route_decision") == "validate" else "failed_recoverable"


def route_after_validate(state: AIStoreAgentState) -> ValidateRoute:
    return "human_review" if _state_value(state, "route_decision") == "human_review" else "failed_recoverable"


__all__ = [
    "DecideRoute", "EntryRoute", "GenerateRoute", "MergeRoute", "ValidateRoute",
    "route_after_merge", "route_after_decide", "route_after_generate",
    "route_after_validate", "route_workflow_entry",
]
