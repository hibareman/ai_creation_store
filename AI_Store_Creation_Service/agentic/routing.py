"""Deterministic routing contracts for the future agentic workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..constants import MAX_REPAIR_ATTEMPTS, WORKFLOW_STATUS_PROCESSING
from .state import AIStoreAgentState


EntryRoute = Literal["understand", "merge_answers", "failed_recoverable"]
DecideRoute = Literal["clarify", "blueprint", "failed_recoverable"]
GenerateRoute = Literal["validate", "failed_recoverable"]
MergeRoute = Literal["understand", "failed_recoverable"]
ValidateRoute = Literal["repair", "human_review", "failed_recoverable"]
RepairRoute = Literal["validate", "failed_recoverable"]


def _state_value(state: AIStoreAgentState, key: str) -> Any:
    if not isinstance(state, Mapping):
        return None
    return state.get(key)


def _repair_attempt_count(state: AIStoreAgentState) -> int | None:
    value = _state_value(state, "repair_attempt_count")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def route_workflow_entry(state: AIStoreAgentState) -> EntryRoute:
    workflow_entry = _state_value(state, "workflow_entry")
    if workflow_entry == "fresh":
        return "understand"
    if workflow_entry == "clarification_resume":
        return "merge_answers"
    return "failed_recoverable"


def route_after_merge(state: AIStoreAgentState) -> MergeRoute:
    if (
        _state_value(state, "current_step") == "merge_answers"
        and _state_value(state, "merge_valid") is True
        and _state_value(state, "status") == WORKFLOW_STATUS_PROCESSING
    ):
        return "understand"
    return "failed_recoverable"


def route_after_decide(state: AIStoreAgentState) -> DecideRoute:
    route_decision = _state_value(state, "route_decision")
    if route_decision == "clarify":
        return "clarify"
    if route_decision == "blueprint":
        return "blueprint"
    return "failed_recoverable"


def route_after_generate(state: AIStoreAgentState) -> GenerateRoute:
    route_decision = _state_value(state, "route_decision")
    if route_decision == "validate":
        return "validate"
    return "failed_recoverable"


def route_after_validate(state: AIStoreAgentState) -> ValidateRoute:
    route_decision = _state_value(state, "route_decision")
    if route_decision == "human_review":
        return "human_review"
    if route_decision == "repair":
        repair_attempt_count = _repair_attempt_count(state)
        if (
            repair_attempt_count is not None
            and 0 <= repair_attempt_count < MAX_REPAIR_ATTEMPTS
        ):
            return "repair"
    return "failed_recoverable"


def route_after_repair(state: AIStoreAgentState) -> RepairRoute:
    route_decision = _state_value(state, "route_decision")
    if route_decision != "validate":
        return "failed_recoverable"
    repair_attempt_count = _repair_attempt_count(state)
    if (
        repair_attempt_count is not None
        and 1 <= repair_attempt_count <= MAX_REPAIR_ATTEMPTS
    ):
        return "validate"
    return "failed_recoverable"


__all__ = [
    "DecideRoute",
    "EntryRoute",
    "GenerateRoute",
    "MergeRoute",
    "RepairRoute",
    "ValidateRoute",
    "route_after_merge",
    "route_after_decide",
    "route_after_generate",
    "route_after_repair",
    "route_after_validate",
    "route_workflow_entry",
]
