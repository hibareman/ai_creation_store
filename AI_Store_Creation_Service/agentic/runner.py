"""Isolated execution boundary for the agentic graph foundation."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..constants import (
    MAX_CLARIFICATION_QUESTIONS_PER_ROUND,
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_APPLIED,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .graph import compile_agentic_graph
from .state import AIStoreAgentState

logger = logging.getLogger(__name__)

_RECURSION_LIMIT = 25
_SAFE_FAILURE_STEP = "recoverable_failure"
_SAFE_FAILURE_MODE = "failed_recoverable"
_SAFE_FAILURE_ROUTE = "failed_recoverable"


def build_initial_agent_state(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    user_store_description: Any,
    normalized_description: Any,
    available_theme_templates: list[str] | None = None,
    clarification_round_count: Any = 0,
    repair_attempt_count: Any = 0,
    validation_errors: list[dict[str, Any]] | None = None,
) -> AIStoreAgentState:
    state: AIStoreAgentState = {
        "workflow_entry": "fresh",
        "store_id": _defensive_copy_input(store_id),
        "tenant_id": _defensive_copy_input(tenant_id),
        "user_id": _defensive_copy_input(user_id),
        "user_store_description": _defensive_copy_input(user_store_description),
        "normalized_description": _defensive_copy_input(normalized_description),
        "clarification_round_count": _defensive_copy_input(
            clarification_round_count
        ),
        "clarification_history": [],
        "clarification_facts": {},
        "merged_personalization_context": {},
        "confirmed_personalization_context": {},
        "answered_target_facts": [],
        "repair_attempt_count": _defensive_copy_input(repair_attempt_count),
    }
    if available_theme_templates is not None:
        state["available_theme_templates"] = _defensive_copy_input(
            available_theme_templates
        )
    if validation_errors is not None:
        state["validation_errors"] = _defensive_copy_input(validation_errors)
    return state


def run_agentic_workflow(
    *,
    store_id: Any,
    tenant_id: Any,
    user_id: Any,
    user_store_description: Any,
    normalized_description: Any,
    available_theme_templates: list[str] | None = None,
    clarification_round_count: Any = 0,
    repair_attempt_count: Any = 0,
    validation_errors: list[dict[str, Any]] | None = None,
) -> AIStoreAgentState:
    initial_state = build_initial_agent_state(
        store_id=store_id,
        tenant_id=tenant_id,
        user_id=user_id,
        user_store_description=user_store_description,
        normalized_description=normalized_description,
        available_theme_templates=available_theme_templates,
        clarification_round_count=clarification_round_count,
        repair_attempt_count=repair_attempt_count,
        validation_errors=validation_errors,
    )

    return _invoke_agentic_graph(initial_state)


def resume_agentic_workflow(
    *,
    prior_state: Mapping[str, Any],
    clarification_answers: Any,
) -> AIStoreAgentState:
    try:
        if not isinstance(prior_state, Mapping):
            raise TypeError("prior_state must be a mapping.")
        initial_state = dict(deepcopy(prior_state))
        _assert_json_serializable(initial_state)
        initial_state["workflow_entry"] = "clarification_resume"
        initial_state["clarification_answers"] = _defensive_copy_input(
            clarification_answers
        )
        _assert_json_serializable(initial_state)
    except Exception:
        return _build_safe_failed_recoverable_state({})
    return _invoke_agentic_graph(initial_state)



def approve_agentic_workflow(*, prior_state: Mapping[str, Any]) -> AIStoreAgentState:
    """Resume a ready-for-review workflow and execute the final Apply Store node."""
    if not isinstance(prior_state, Mapping):
        return _build_safe_failed_recoverable_state({})
    initial_state = dict(deepcopy(prior_state))
    if not _is_ready_for_review_terminal(initial_state):
        return _build_safe_failed_recoverable_state(initial_state)
    initial_state["workflow_entry"] = "review_approval"
    initial_state["review_approved"] = True
    result = _invoke_agentic_graph(initial_state)
    return result

def validate_agentic_terminal_state(state: Any) -> AIStoreAgentState:
    try:
        terminal_state = _coerce_plain_state(state)
        valid_state = _validated_terminal_state(terminal_state)
        if valid_state is None:
            raise ValueError
        return _json_defensive_copy(valid_state)
    except Exception as exc:
        raise ValueError("Invalid agentic terminal state.") from exc


def build_safe_agentic_failure_state(
    *,
    store_id: Any = None,
    tenant_id: Any = None,
    user_id: Any = None,
    user_store_description: Any = "",
    normalized_description: Any = "",
    clarification_round_count: Any = 0,
    repair_attempt_count: Any = 0,
) -> AIStoreAgentState:
    return _build_safe_failed_recoverable_state(
        {
            "store_id": store_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_store_description": user_store_description,
            "normalized_description": normalized_description,
            "clarification_round_count": clarification_round_count,
            "repair_attempt_count": repair_attempt_count,
        }
    )


def _invoke_agentic_graph(initial_state: AIStoreAgentState) -> AIStoreAgentState:
    try:
        graph = compile_agentic_graph()
        graph_result = graph.invoke(
            deepcopy(initial_state),
            config={"recursion_limit": _RECURSION_LIMIT},
        )
        terminal_state = _coerce_plain_state(graph_result)
        valid_state = _validated_terminal_state(terminal_state)

        if valid_state is None:
                logger.error(
                    "Agentic graph returned an invalid terminal state | "
                    "store_id=%s | tenant_id=%s | graph_result=%s",
                    initial_state.get("store_id"),
                    initial_state.get("tenant_id"),
                    json.dumps(
                        terminal_state,
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                return _build_safe_failed_recoverable_state(initial_state)
        return valid_state

    except Exception as exc:
        logger.exception(
            "AI store workflow execution failed | store_id=%s | tenant_id=%s",
            initial_state.get("store_id"),
            initial_state.get("tenant_id"),
        )

        state = _build_safe_failed_recoverable_state(initial_state)
        state["developer_message"] = f"{type(exc).__name__}: {exc}"
        state["error_code"] = type(exc).__name__

        return state


def _defensive_copy_input(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    return value


def _coerce_plain_state(value: Any) -> AIStoreAgentState:
    if not isinstance(value, Mapping):
        raise TypeError("Graph result must be a mapping.")
    plain_state = dict(value)
    _assert_json_serializable(plain_state)
    return plain_state


def _build_safe_failed_recoverable_state(
    initial_state: Mapping[str, Any],
) -> AIStoreAgentState:
    fallback_state: AIStoreAgentState = {
        "store_id": _safe_identity_value(initial_state.get("store_id")),
        "workflow_entry": _safe_workflow_entry(initial_state.get("workflow_entry")),
        "tenant_id": _safe_identity_value(initial_state.get("tenant_id")),
        "user_id": _safe_identity_value(initial_state.get("user_id")),
        "user_store_description": _safe_text_value(
            initial_state.get("user_store_description")
        ),
        "normalized_description": _safe_text_value(
            initial_state.get("normalized_description")
        ),
        "clarification_round_count": _safe_counter(
            initial_state.get("clarification_round_count")
        ),
        "clarification_history": _safe_json_value(
            initial_state.get("clarification_history"),
            [],
        ),
        "clarification_facts": _safe_json_value(
            initial_state.get("clarification_facts"),
            {},
        ),
        "merged_personalization_context": _safe_json_value(
            initial_state.get("merged_personalization_context"),
            {},
        ),
        "confirmed_personalization_context": _safe_json_value(
            initial_state.get("confirmed_personalization_context"),
            {},
        ),
        "answered_target_facts": _safe_json_value(
            initial_state.get("answered_target_facts"),
            [],
        ),
        "repair_attempt_count": min(
            _safe_counter(initial_state.get("repair_attempt_count")),
            MAX_REPAIR_ATTEMPTS,
        ),
        "clarification_questions": [],
        "missing_information": [],
        "confidence_score": 0,
        "current_step": _SAFE_FAILURE_STEP,
        "mode": _SAFE_FAILURE_MODE,
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "route_decision": _SAFE_FAILURE_ROUTE,
        "error_code": _safe_error_text(
            initial_state.get("error_code"),
            RECOVERABLE_FAILURE_ERROR_CODE,
        ),
        "user_message": _safe_error_text(
            initial_state.get("user_message"),
            RECOVERABLE_FAILURE_USER_MESSAGE,
        ),
        "developer_message": _safe_text_value(initial_state.get("developer_message")),
    }
    _assert_json_serializable(fallback_state)
    return fallback_state


def _safe_identity_value(value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)) or value is None:
        return value
    return None


def _safe_text_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _safe_error_text(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _safe_counter(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _safe_workflow_entry(value: Any) -> str:
    if value in {"fresh", "clarification_resume", "review_approval"}:
        return value
    return "fresh"


def _safe_json_value(value: Any, default: Any) -> Any:
    try:
        _assert_json_serializable(value)
    except (TypeError, ValueError):
        return deepcopy(default)
    return deepcopy(value)


def _assert_json_serializable(value: Any) -> None:
    json.dumps(value)


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _validated_terminal_state(state: AIStoreAgentState) -> AIStoreAgentState | None:
    if not _has_valid_serialized_shape(state):
        return None
    if _is_completed_terminal(state):
        return state
    if state.get("status") == WORKFLOW_STATUS_APPLIED:
        return None
    if not _has_valid_counters(state):
        return None
    if _is_ready_for_review_terminal(state):
        return state
    if _is_needs_clarification_terminal(state):
        return state
    if _is_failed_recoverable_terminal(state):
        return _canonicalize_failed_recoverable_state(state)
    return None


def _has_valid_serialized_shape(state: AIStoreAgentState) -> bool:
    try:
        _assert_json_serializable(state)
    except TypeError:
        return False
    return isinstance(state, dict)


def _has_valid_counters(state: AIStoreAgentState) -> bool:
    clarification_count = state.get("clarification_round_count")
    repair_count = state.get("repair_attempt_count")
    if clarification_count is not None and not _is_non_negative_int(clarification_count):
        return False
    if repair_count is not None:
        if not _is_non_negative_int(repair_count):
            return False
        if repair_count > MAX_REPAIR_ATTEMPTS:
            return False
    if clarification_count is not None and clarification_count > MAX_CLARIFICATION_ROUNDS:
        return False
    return True


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_completed_terminal(state: AIStoreAgentState) -> bool:
    return (
        state.get("status") == "completed"
        and state.get("current_step") == "completed"
        and state.get("mode") == "completed"
        and state.get("route_decision") == "completed"
        and state.get("application_success") is True
        and isinstance(state.get("created_categories_count"), int)
        and isinstance(state.get("created_products_count"), int)
        and isinstance(state.get("completed_at"), str)
    )


def _is_ready_for_review_terminal(state: AIStoreAgentState) -> bool:
    draft_payload = state.get("draft_payload")
    return (
        state.get("current_step") == WORKFLOW_STATUS_READY_FOR_REVIEW
        and state.get("mode") == "draft_ready"
        and state.get("status") == WORKFLOW_STATUS_READY_FOR_REVIEW
        and state.get("route_decision") == "human_review"
        and state.get("clarification_questions", []) == []
        and _has_no_validation_errors(state)
        and _is_draft_ready_payload(draft_payload)
    )


def _is_needs_clarification_terminal(state: AIStoreAgentState) -> bool:
    draft_payload = state.get("draft_payload")
    state_questions = state.get("clarification_questions")
    return (
        state.get("current_step")
        in {"human_review", WORKFLOW_STATUS_NEEDS_CLARIFICATION}
        and state.get("mode") == "clarification"
        and state.get("status") == WORKFLOW_STATUS_NEEDS_CLARIFICATION
        and state.get("route_decision") == "human_review"
        and _has_no_validation_errors(state)
        and _is_valid_mcq_list(state_questions)
        and _is_clarification_payload(draft_payload)
        and state_questions == draft_payload.get("clarification_questions")
    )


def _is_failed_recoverable_terminal(state: AIStoreAgentState) -> bool:
    return (
        state.get("current_step") == _SAFE_FAILURE_STEP
        and state.get("mode") == _SAFE_FAILURE_MODE
        and state.get("status") == WORKFLOW_STATUS_FAILED_RECOVERABLE
        and state.get("route_decision") == _SAFE_FAILURE_ROUTE
        and state.get("clarification_questions", []) == []
    )


def _canonicalize_failed_recoverable_state(
    state: AIStoreAgentState,
) -> AIStoreAgentState:
    canonical_state: AIStoreAgentState = {
        "store_id": _safe_identity_value(state.get("store_id")),
        "workflow_entry": _safe_workflow_entry(state.get("workflow_entry")),
        "tenant_id": _safe_identity_value(state.get("tenant_id")),
        "user_id": _safe_identity_value(state.get("user_id")),
        "user_store_description": _safe_text_value(
            state.get("user_store_description")
        ),
        "normalized_description": _safe_text_value(state.get("normalized_description")),
        "clarification_round_count": _safe_counter(
            state.get("clarification_round_count")
        ),
        "clarification_history": _safe_json_value(
            state.get("clarification_history"),
            [],
        ),
        "clarification_facts": _safe_json_value(
            state.get("clarification_facts"),
            {},
        ),
        "repair_attempt_count": min(
            _safe_counter(state.get("repair_attempt_count")),
            MAX_REPAIR_ATTEMPTS,
        ),
        "clarification_questions": [],
        "current_step": _SAFE_FAILURE_STEP,
        "mode": _SAFE_FAILURE_MODE,
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "route_decision": _SAFE_FAILURE_ROUTE,
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }
    for field_name, default in (
        ("description_personalization_facts", {}),
        ("effective_personalization_context", {}),
        ("missing_core_personalization_keys", []),
        ("ambiguous_personalization_keys", []),
        ("additional_blocking_missing_information", []),
        ("personalization_progress", {}),
    ):
        if field_name in state:
            canonical_state[field_name] = _safe_json_value(
                state.get(field_name),
                default,
            )
    if isinstance(state.get("personalization_core_complete"), bool):
        canonical_state["personalization_core_complete"] = state[
            "personalization_core_complete"
        ]
    if "feedback" in state:
        canonical_state["feedback"] = _safe_json_value(state.get("feedback"), {})
    _assert_json_serializable(canonical_state)
    return canonical_state


def _is_draft_ready_payload(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("clarification_needed") is False
        and value.get("clarification_questions", []) == []
    )


def _is_clarification_payload(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("clarification_needed") is True
        and _is_valid_mcq_list(value.get("clarification_questions"))
    )


def _has_no_validation_errors(state: AIStoreAgentState) -> bool:
    return "validation_errors" in state and state.get("validation_errors") == []


def _is_valid_mcq_list(value: Any) -> bool:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_CLARIFICATION_QUESTIONS_PER_ROUND
    ):
        return False
    return all(_is_valid_mcq_question(question) for question in value)


def _is_valid_mcq_question(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False

    required_fields = {
        "question_key",
        "question_text",
        "options",
        "other_option",
    }
    if not required_fields.issubset(value):
        return False

    question_key = value.get("question_key")
    question_text = value.get("question_text")
    options = value.get("options")
    other_option = value.get("other_option")

    if not (
        isinstance(question_key, str)
        and bool(question_key.strip())
        and isinstance(question_text, str)
        and bool(question_text.strip())
        and isinstance(options, list)
        and 3 <= len(options) <= 5
        and isinstance(other_option, str)
        and bool(other_option.strip())
        and all(isinstance(option, str) and option.strip() for option in options)
    ):
        return False

    optional_string_fields = (
        "question_id",
        "target_fact",
        "reason",
        "answer_type",
    )
    for field_name in optional_string_fields:
        if field_name in value:
            field_value = value.get(field_name)
            if not isinstance(field_value, str) or not field_value.strip():
                return False

    # Recommendation is optional and may legitimately be null.
    if "recommendation" in value:
        recommendation = value.get("recommendation")
        if recommendation is not None and (
            not isinstance(recommendation, str) or not recommendation.strip()
        ):
            return False

    for field_name in ("allow_custom_answer", "required"):
        if field_name in value and not isinstance(value.get(field_name), bool):
            return False

    normalized_options = [
        " ".join(option.strip().split()).casefold() for option in options
    ]
    normalized_other = " ".join(other_option.strip().split()).casefold()
    return (
        len(set(normalized_options)) == len(normalized_options)
        and normalized_options.count(normalized_other) == 1
        and normalized_options[-1] == normalized_other
    )


__all__ = [
    "approve_agentic_workflow",
    "build_safe_agentic_failure_state",
    "build_initial_agent_state",
    "resume_agentic_workflow",
    "run_agentic_workflow",
    "validate_agentic_terminal_state",
]