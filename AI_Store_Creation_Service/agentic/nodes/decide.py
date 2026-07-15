"""Deterministic Decide node for semantic-understanding routing."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_CLARIFICATION_ROUNDS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState
from ..understanding import validate_semantic_analysis_payload


_ANALYSIS_KEYS = (
    "description_language",
    "description_sufficient",
    "detected_store_domains",
    "business_summary",
    "target_audience",
    "product_direction",
    "blocking_missing_information",
    "ambiguities",
)


def decide_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        analysis = _validated_analysis_from_state(state)
    except Exception:
        return _safe_decision_failure()

    if analysis["description_sufficient"] is True:
        route_decision = "blueprint"
    else:
        clarification_round_count = _validated_clarification_count(state)
        route_decision = (
            "clarify"
            if clarification_round_count < MAX_CLARIFICATION_ROUNDS
            else "failed_recoverable"
        )
    return {
        "current_step": "decide",
        "status": WORKFLOW_STATUS_PROCESSING,
        "route_decision": route_decision,
    }


def _validated_analysis_from_state(state: AIStoreAgentState) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise ValueError("State must be a mapping.")
    if state.get("understanding_valid") is not True:
        raise ValueError("Understanding must be valid.")

    word_count = state.get("description_word_count")
    if isinstance(word_count, bool) or not isinstance(word_count, int) or word_count < 0:
        raise ValueError("description_word_count must be a non-negative integer.")

    reasons = state.get("understanding_reasons")
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(reason, str) and reason.strip() for reason in reasons)
    ):
        raise ValueError("understanding_reasons must be non-empty strings.")

    candidate = {key: deepcopy(state[key]) for key in _ANALYSIS_KEYS}
    return validate_semantic_analysis_payload(
        candidate,
        clarification_facts=state.get("clarification_facts", {}),
    )


def _validated_clarification_count(state: AIStoreAgentState) -> int:
    value = state.get("clarification_round_count", 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("clarification_round_count must be an integer.")
    if value < 0 or value > MAX_CLARIFICATION_ROUNDS:
        raise ValueError("clarification_round_count is outside the limit.")
    return value


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
