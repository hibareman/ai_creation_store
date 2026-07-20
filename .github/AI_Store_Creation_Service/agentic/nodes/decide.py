"""Deterministic Decide node for personalization-aware routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...constants import (
    MAX_CLARIFICATION_ROUNDS,
    PERSONALIZATION_INCOMPLETE_ERROR_CODE,
    PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState


def decide_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        assessment = _validated_personalization_assessment(state)
    except Exception:
        return _safe_decision_failure()

    missing_core = assessment["missing_core_personalization_keys"]
    ambiguous_core = assessment["ambiguous_personalization_keys"]
    blocking = assessment["additional_blocking_missing_information"]
    round_count = assessment["clarification_round_count"]

    needs_core_clarification = bool(missing_core or ambiguous_core)
    needs_adaptive_clarification = bool(blocking)

    if needs_core_clarification:
        # Completed rounds 1 and 2 are the only rounds allowed for core keys.
        if round_count >= MAX_CLARIFICATION_ROUNDS - 1:
            return _personalization_incomplete_failure()
        route_decision = "clarify"
    elif needs_adaptive_clarification:
        # Round 3 is reserved for unresolved adaptive blocking information.
        if round_count >= MAX_CLARIFICATION_ROUNDS:
            return _personalization_incomplete_failure()
        route_decision = "clarify"
    else:
        route_decision = "generate"

    return {
        "current_step": "decide",
        "status": WORKFLOW_STATUS_PROCESSING,
        "route_decision": route_decision,
    }


def _validated_personalization_assessment(state: AIStoreAgentState) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise ValueError("State must be a mapping.")
    if state.get("understanding_valid") is not True:
        raise ValueError("Understanding must be valid.")

    clarification_round_count = state.get("clarification_round_count", 0)
    if isinstance(clarification_round_count, bool) or not isinstance(
        clarification_round_count, int
    ):
        raise ValueError("clarification_round_count must be an integer.")
    if clarification_round_count < 0 or clarification_round_count > MAX_CLARIFICATION_ROUNDS:
        raise ValueError("clarification_round_count is outside the limit.")

    missing_keys = _validated_string_list(
        state.get("missing_core_personalization_keys"),
        field_name="missing_core_personalization_keys",
    )
    ambiguous_keys = _validated_string_list(
        state.get("ambiguous_personalization_keys"),
        field_name="ambiguous_personalization_keys",
    )
    blocking = _validated_string_list(
        state.get("additional_blocking_missing_information"),
        field_name="additional_blocking_missing_information",
    )

    return {
        "missing_core_personalization_keys": missing_keys,
        "ambiguous_personalization_keys": ambiguous_keys,
        "additional_blocking_missing_information": blocking,
        "clarification_round_count": clarification_round_count,
    }


def _validated_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings.")
    return list(value)


def _personalization_incomplete_failure() -> dict[str, Any]:
    return {
        "current_step": "decide",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "error_code": PERSONALIZATION_INCOMPLETE_ERROR_CODE,
        "user_message": PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
    }


def _safe_decision_failure() -> dict[str, Any]:
    return {
        "current_step": "decide",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


__all__ = ["decide_node"]
