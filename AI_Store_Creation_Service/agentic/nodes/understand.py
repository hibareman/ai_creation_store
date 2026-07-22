"""AI-backed Understand node with deterministic personalization assessment."""

from __future__ import annotations

import json
import logging
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
from ..personalization import build_personalization_understanding
from ..state import AIStoreAgentState
from ..understanding import analyze_store_description, count_description_words

logger = logging.getLogger(__name__)


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
        _validate_identity(state.get("store_id"))
        _validate_identity(state.get("tenant_id"))
        _validate_identity(state.get("user_id"))
        description = state.get("normalized_description", "")
        if not isinstance(description, str):
            raise ValueError("normalized_description must be a string.")
        description = " ".join(description.strip().split())
        if not description:
            raise ValueError("normalized_description is required.")
        clarification_facts = state.get("clarification_facts", {})
        analysis = analyze_store_description(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            user_id=state.get("user_id"),
            normalized_description=description,
            clarification_history=state.get("clarification_history", []),
            clarification_facts=clarification_facts,
            clarification_round_count=state.get("clarification_round_count", 0),
        )
        personalization_update = build_personalization_understanding(
            description,
            ai_personalization_facts=analysis["personalization"],
            clarification_facts=clarification_facts,
            semantic_blocking_missing_information=analysis[
                "blocking_missing_information"
            ],
        )
        reasons = (
            ["ai_semantic_analysis_sufficient"]
            if analysis["description_sufficient"] is True
            else ["ai_semantic_analysis_requires_clarification"]
        )
        if analysis["description_language"] == "unknown":
            reasons.append("ai_semantic_analysis_unknown_language")
        combined_description_sufficient = bool(
            analysis["description_sufficient"]
            and personalization_update["personalization_core_complete"]
            and not personalization_update[
                "additional_blocking_missing_information"
            ]
        )

        update: dict[str, Any] = {
            "current_step": "understand",
            "status": WORKFLOW_STATUS_PROCESSING,
            "understanding_valid": True,
            "description_word_count": count_description_words(description),
            "understanding_reasons": reasons,
            "clarification_questions": [],
            **deepcopy(analysis),
            **personalization_update,
            "description_sufficient": combined_description_sufficient,
        }
        if "validation_errors" not in state:
            update["validation_errors"] = []
        json.dumps(update, ensure_ascii=False, allow_nan=False)
        return update
    except Exception as exc:
        logger.exception(
            "AI understanding failed | store_id=%s | tenant_id=%s | "
            "error_type=%s | error=%r",
            state.get("store_id"),
            state.get("tenant_id"),
            type(exc).__name__,
            exc,
        )
        return _safe_understanding_failure_update(state)


def _validate_identity(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Agentic identity values must be positive integers.")


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
        "target_audience": "",
        "product_direction": [],
        "blocking_missing_information": [],
        "missing_information": [],
        "confidence_score": 0,
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
