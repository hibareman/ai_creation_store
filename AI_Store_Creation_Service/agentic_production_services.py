"""Production bridge for agentic AI Store Creation service integration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django.core.exceptions import ValidationError

from .agentic_session_services import (
    get_cached_agentic_workflow,
    resume_cached_agentic_workflow,
    start_cached_agentic_workflow,
)
from .constants import (
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .selectors import get_available_theme_template_names, get_store_for_ai_flow
from .validators import build_ai_recoverable_failure_payload, validate_initial_description
from .workflow_services import (
    create_draft_store_for_ai_flow,
    derive_store_name_from_description,
)


_PUBLIC_RESPONSE_KEYS = {"store_id", "draft_payload", "draft_metadata"}
_INTERNAL_RESPONSE_KEYS = {
    "tenant_id",
    "user_id",
    "workflow_entry",
    "description_language",
    "description_word_count",
    "detected_store_domains",
    "description_sufficient",
    "understanding_valid",
    "understanding_reasons",
    "business_summary",
    "target_audience",
    "product_direction",
    "blocking_missing_information",
    "ambiguities",
    "clarification_facts",
    "clarification_answers",
    "choices",
    "prompt",
    "provider_response",
    "available_theme_templates",
}


def start_agentic_ai_draft_workflow(
    *,
    user,
    tenant_id: int | None,
    user_store_description: str,
) -> dict[str, Any]:
    normalized_description = validate_initial_description(user_store_description)
    derived_name = derive_store_name_from_description(normalized_description)
    store = create_draft_store_for_ai_flow(
        user=user,
        tenant_id=tenant_id,
        name=derived_name,
        description=normalized_description,
    )
    theme_names = list(get_available_theme_template_names())
    user_id = _authenticated_user_id_or_raise(user)

    state = start_cached_agentic_workflow(
        store_id=store.id,
        tenant_id=store.tenant_id,
        user_id=user_id,
        user_store_description=user_store_description,
        normalized_description=normalized_description,
        available_theme_templates=theme_names,
    )
    return _project_agentic_state_to_public_response(state)


def get_current_agentic_ai_draft(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    state = get_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    if state is None:
        raise ValidationError("No active agentic AI session found for this store")
    return _project_agentic_state_to_public_response(state)


def process_agentic_clarification_round(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
    clarification_answers: Any,
) -> dict[str, Any]:
    state = get_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    if state is None:
        return build_ai_recoverable_failure_payload()

    resumed_state = resume_cached_agentic_workflow(
        store_id=state["store_id"],
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        clarification_answers=clarification_answers,
    )
    return _project_agentic_state_to_public_response(resumed_state)["draft_payload"]


def get_existing_agentic_session(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any] | None:
    store = _get_authorized_store_or_raise(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    user_id = _authenticated_user_id_or_raise(user)
    state = get_cached_agentic_workflow(
        store_id=store.id,
        tenant_id=store.tenant_id,
        user_id=user_id,
    )
    if state is None:
        return None
    if not _state_identity_matches(
        state=state,
        store_id=store.id,
        tenant_id=store.tenant_id,
        user_id=user_id,
    ):
        raise ValidationError("Store not found or access denied")
    return _json_defensive_copy(state)


def has_existing_agentic_session(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> bool:
    return (
        get_existing_agentic_session(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
        )
        is not None
    )


def _get_authorized_store_or_raise(*, store_id: int, user, tenant_id: int | None):
    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=tenant_id)
    if store is None:
        raise ValidationError("Store not found or access denied")
    return store


def _authenticated_user_id_or_raise(user) -> int:
    user_id = getattr(user, "id", None)
    if (
        not getattr(user, "is_authenticated", False)
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise ValidationError("Authentication required")
    return user_id


def _project_agentic_state_to_public_response(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        return _project_failure_state({})

    status = state.get("status")
    if status == WORKFLOW_STATUS_FAILED_RECOVERABLE:
        return _project_failure_state(state)
    if status == WORKFLOW_STATUS_NEEDS_CLARIFICATION:
        return _project_draft_state(
            state=state,
            clarification_needed=True,
            clarification_questions=state.get("clarification_questions"),
        )
    if status == WORKFLOW_STATUS_READY_FOR_REVIEW:
        return _project_draft_state(
            state=state,
            clarification_needed=False,
            clarification_questions=[],
        )
    return _project_failure_state(state)


def _project_draft_state(
    *,
    state: Mapping[str, Any],
    clarification_needed: bool,
    clarification_questions: Any,
) -> dict[str, Any]:
    draft_payload = state.get("draft_payload")
    if not isinstance(draft_payload, Mapping):
        return _project_failure_state(state)

    projected_payload = _json_defensive_copy(dict(draft_payload))
    projected_payload["clarification_needed"] = clarification_needed
    projected_payload["clarification_questions"] = _safe_question_list(
        clarification_questions
    )
    if clarification_needed and not projected_payload["clarification_questions"]:
        return _project_failure_state(state)

    return _json_defensive_copy(
        {
            "store_id": state.get("store_id"),
            "draft_payload": projected_payload,
            "draft_metadata": _project_metadata(state),
        }
    )


def _project_failure_state(state: Mapping[str, Any]) -> dict[str, Any]:
    error_code = _safe_text(
        state.get("error_code"),
        default=RECOVERABLE_FAILURE_ERROR_CODE,
    )
    user_message = _safe_text(
        state.get("user_message"),
        default=RECOVERABLE_FAILURE_USER_MESSAGE,
    )
    return _json_defensive_copy(
        {
            "store_id": state.get("store_id"),
            "draft_payload": build_ai_recoverable_failure_payload(
                error_code=error_code,
                user_message=user_message,
            ),
            "draft_metadata": _project_metadata(
                {
                    **dict(state),
                    "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                    "current_step": "recoverable_failure",
                    "mode": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                    "is_fallback": True,
                    "error_code": error_code,
                    "user_message": user_message,
                }
            ),
        }
    )


def _project_metadata(state: Mapping[str, Any]) -> dict[str, Any]:
    status = _safe_text(
        state.get("status"),
        default=WORKFLOW_STATUS_FAILED_RECOVERABLE,
    )
    metadata: dict[str, Any] = {
        "status": status,
        "current_step": _safe_text(state.get("current_step"), default="human_review"),
        "mode": _safe_text(state.get("mode"), default=status),
        "is_fallback": status == WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "clarification_round_count": _safe_counter(
            state.get("clarification_round_count")
        ),
        "repair_attempt_count": _safe_counter(state.get("repair_attempt_count")),
        "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "workflow_engine": "agentic",
    }
    if status == WORKFLOW_STATUS_FAILED_RECOVERABLE:
        metadata["error_code"] = _safe_text(
            state.get("error_code"),
            default=RECOVERABLE_FAILURE_ERROR_CODE,
        )
        metadata["user_message"] = _safe_text(
            state.get("user_message"),
            default=RECOVERABLE_FAILURE_USER_MESSAGE,
        )
    return _json_defensive_copy(metadata)


def _state_identity_matches(
    *,
    state: Mapping[str, Any],
    store_id: int,
    tenant_id: int,
    user_id: int,
) -> bool:
    return (
        state.get("store_id") == store_id
        and state.get("tenant_id") == tenant_id
        and state.get("user_id") == user_id
    )


def _safe_counter(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _safe_text(value: Any, *, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _safe_question_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return _json_defensive_copy(value)


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(deepcopy(value), ensure_ascii=False, allow_nan=False))


__all__ = [
    "get_current_agentic_ai_draft",
    "get_existing_agentic_session",
    "has_existing_agentic_session",
    "process_agentic_clarification_round",
    "start_agentic_ai_draft_workflow",
]
