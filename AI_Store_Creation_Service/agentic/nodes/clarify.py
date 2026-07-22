"""Deterministic clarification planner plus provider-backed question wording."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ...constants import (
    MAX_CLARIFICATION_ROUNDS,
    PERSONALIZATION_INCOMPLETE_ERROR_CODE,
    PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
)
from ..clarifying import generate_clarification_questions
from ..personalization import (
    build_clarification_question_specs,
    has_unresolved_personalization_blockers,
    select_clarification_question_keys,
)
from ..state import AIStoreAgentState


def clarify_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        if state.get("description_sufficient") is not False:
            raise ValueError("Clarify requires insufficient personalization analysis.")

        round_count = _validate_round_count(
            state.get("clarification_round_count", 0)
        )
        if round_count >= MAX_CLARIFICATION_ROUNDS:
            return _safe_clarify_failure_update(
                error_code=PERSONALIZATION_INCOMPLETE_ERROR_CODE,
                user_message=PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
            )
        additional_blocking = _combined_blocking_keys(state)
        requested_keys = select_clarification_question_keys(
            description_personalization_facts=state.get(
                "description_personalization_facts", {}
            ),
            clarification_facts=state.get("clarification_facts", {}),
            missing_core_personalization_keys=state.get(
                "missing_core_personalization_keys", []
            ),
            ambiguous_personalization_keys=state.get(
                "ambiguous_personalization_keys", []
            ),
            additional_blocking_missing_information=additional_blocking,
            clarification_round_count=round_count,
            clarification_history=state.get("clarification_history", []),
        )

        blockers_remain = has_unresolved_personalization_blockers(
            missing_core_personalization_keys=state.get(
                "missing_core_personalization_keys", []
            ),
            ambiguous_personalization_keys=state.get(
                "ambiguous_personalization_keys", []
            ),
            additional_blocking_missing_information=additional_blocking,
        )
        if not requested_keys:
            if blockers_remain or round_count >= MAX_CLARIFICATION_ROUNDS:
                return _safe_clarify_failure_update(
                    error_code=PERSONALIZATION_INCOMPLETE_ERROR_CODE,
                    user_message=PERSONALIZATION_INCOMPLETE_USER_MESSAGE,
                )
            raise ValueError("No clarification question keys were selected.")

        question_specs = build_clarification_question_specs(requested_keys)
        questions = generate_clarification_questions(
            store_id=state.get("store_id"),
            tenant_id=state.get("tenant_id"),
            user_id=state.get("user_id"),
            normalized_description=state.get("normalized_description"),
            description_language=state.get("description_language"),
            detected_store_domains=state.get("detected_store_domains", []),
            target_audience=state.get("target_audience", ""),
            product_direction=state.get("product_direction", []),
            blocking_missing_information=requested_keys,
            ambiguities=state.get("ambiguities", []),
            clarification_round_count=round_count,
            clarification_history=state.get("clarification_history", []),
            clarification_facts=state.get("clarification_facts", {}),
            requested_question_keys=requested_keys,
            requested_question_specs=question_specs,
            effective_personalization_context=state.get(
                "effective_personalization_context", {}
            ),
        )
        state_questions = deepcopy(questions)
        payload_questions = deepcopy(questions)
        update = {
            "current_step": "clarify",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "mode": "clarification",
            "route_decision": "human_review",
            "validation_errors": [],
            "clarification_requested_keys": deepcopy(requested_keys),
            "clarification_question_specs": deepcopy(question_specs),
            "clarification_questions": state_questions,
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": payload_questions,
            },
        }
        json.dumps(update, ensure_ascii=False, allow_nan=False)
        return update
    except Exception:
        return _safe_clarify_failure_update()


def _combined_blocking_keys(state: AIStoreAgentState) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for field_name in (
        "additional_blocking_missing_information",
        "blocking_missing_information",
    ):
        value = state.get(field_name, [])
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list.")
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} items must be strings.")
            key = item.strip()
            if key and key not in seen:
                seen.add(key)
                combined.append(key)
    return combined


def _validate_round_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("clarification_round_count must be an integer.")
    if value < 0 or value > MAX_CLARIFICATION_ROUNDS:
        raise ValueError("clarification_round_count is outside the allowed range.")
    return value


def _safe_clarify_failure_update(
    *,
    error_code: str = RECOVERABLE_FAILURE_ERROR_CODE,
    user_message: str = RECOVERABLE_FAILURE_USER_MESSAGE,
) -> dict[str, Any]:
    return {
        "current_step": "clarify",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "validation_errors": [],
        "clarification_requested_keys": [],
        "clarification_question_specs": [],
        "clarification_questions": [],
        "draft_payload": {},
        "error_code": error_code,
        "user_message": user_message,
    }


__all__ = ["clarify_node"]
