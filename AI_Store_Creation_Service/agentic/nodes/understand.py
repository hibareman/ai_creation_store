"""AI-backed Understand node for the agentic AI Store Creation graph."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..state import AIStoreAgentState
from ..understanding import analyze_store_description, count_description_words


def _safe_counter(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value >= 0 else 0


def _safe_clarification_count(value: Any) -> int:
    return min(_safe_counter(value), MAX_CLARIFICATION_ROUNDS)


def _safe_repair_count(value: Any) -> int:
    return min(_safe_counter(value), MAX_REPAIR_ATTEMPTS)


def understand_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        analysis = analyze_store_description(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            user_id=state.get("user_id"),
            normalized_description=state.get("normalized_description"),
            clarification_history=state.get("clarification_history", []),
            clarification_facts=state.get("clarification_facts", {}),
            clarification_round_count=state.get("clarification_round_count", 0),
        )
        reasons = (
            ["ai_semantic_analysis_sufficient"]
            if analysis["description_sufficient"] is True
            else ["ai_semantic_analysis_requires_clarification"]
        )
        if analysis["description_language"] == "unknown":
            reasons.append("ai_semantic_analysis_unknown_language")

        update: dict[str, Any] = {
            "current_step": "understand",
            "status": WORKFLOW_STATUS_PROCESSING,
            "understanding_valid": True,
            "description_word_count": count_description_words(
                state.get("normalized_description", "")
            ),
            "understanding_reasons": reasons,
            "clarification_questions": [],
            **deepcopy(analysis),
        }
        if "validation_errors" not in state:
            update["validation_errors"] = []
        json.dumps(update, ensure_ascii=False, allow_nan=False)
        return update
    except Exception:
        return _safe_understanding_failure_update(state)


def _safe_understanding_failure_update(state: AIStoreAgentState) -> dict[str, Any]:
    update: dict[str, Any] = {
        "current_step": "understand",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "understanding_valid": False,
        "description_sufficient": False,
        "description_language": "unknown",
        "description_word_count": count_description_words(
            state.get("normalized_description", "")
        ),
        "detected_store_domains": [],
        "business_summary": "",
        "target_audience": "",
        "product_direction": [],
        "blocking_missing_information": [],
        "ambiguities": [],
        "clarification_questions": [],
        "understanding_reasons": ["ai_semantic_analysis_failed"],
        "draft_payload": {},
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
        "clarification_round_count": _safe_clarification_count(
            state.get("clarification_round_count")
        ),
        "repair_attempt_count": _safe_repair_count(state.get("repair_attempt_count")),
    }
    if "validation_errors" not in state:
        update["validation_errors"] = []
    return update


__all__ = ["understand_node"]
