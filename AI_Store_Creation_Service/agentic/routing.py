"""Small deterministic routers for the simplified workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..constants import WORKFLOW_STATUS_PROCESSING
from .state import AIStoreAgentState

EntryRoute = Literal["understand", "merge_answers", "apply_store", "failed_recoverable"]
DecideRoute = Literal["clarify", "generate", "failed_recoverable"]
BlueprintRoute = Literal["generate", "failed_recoverable"]
GenerateRoute = Literal["validate", "failed_recoverable"]
MergeRoute = Literal["understand", "failed_recoverable"]
ValidateRoute = Literal["human_review", "repair", "failed_recoverable"]
RepairRoute = Literal["validate", "failed_recoverable"]


def _state_value(state: AIStoreAgentState, key: str) -> Any:
    return state.get(key) if isinstance(state, Mapping) else None


def route_workflow_entry(state: AIStoreAgentState) -> EntryRoute:
    entry = _state_value(state, "workflow_entry")
    if entry == "review_approval":
        return "apply_store"
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


def route_after_blueprint(state: AIStoreAgentState) -> BlueprintRoute:
    return "generate" if _state_value(state, "route_decision") == "generate" and isinstance(_state_value(state, "blueprint"), Mapping) else "failed_recoverable"

def route_after_generate(state: AIStoreAgentState) -> GenerateRoute:
    return "validate" if _state_value(state, "route_decision") == "validate" else "failed_recoverable"


def route_after_validate(state: AIStoreAgentState) -> ValidateRoute:
    decision = _state_value(state, "route_decision")
    if decision in {"human_review", "repair"}:
        return decision
    return "failed_recoverable"


def route_after_repair(state: AIStoreAgentState) -> RepairRoute:
    return "validate" if _state_value(state, "route_decision") == "validate" else "failed_recoverable"


__all__ = [
    "DecideRoute", "EntryRoute", "GenerateRoute", "MergeRoute", "RepairRoute", "ValidateRoute",
    "route_after_merge", "route_after_decide", "route_after_blueprint", "route_after_generate",
    "route_after_validate", "route_after_repair", "route_workflow_entry",
]
