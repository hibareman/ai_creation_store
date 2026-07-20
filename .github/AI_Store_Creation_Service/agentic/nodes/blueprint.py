"""Deterministic personalization-constrained Blueprint node."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from ...constants import (
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_PROCESSING,
)
from ..blueprinting import AIBlueprintValidationError, build_store_blueprint
from ..diagnostics import (
    GENERATION_FAILURE_LOG_MESSAGE,
    mark_failure_category,
    safe_exception_class_name,
    safe_exception_info,
    safe_identity_for_log,
)
from ..state import AIStoreAgentState


logger = logging.getLogger(__name__)


def blueprint_node(state: AIStoreAgentState) -> dict[str, Any]:
    """Create a locked Store Blueprint only after personalization is complete."""

    try:
        _validate_blueprint_entry_state(state)
        blueprint = build_store_blueprint(
            normalized_description=state.get("normalized_description"),
            description_personalization_facts=state.get(
                "description_personalization_facts"
            ),
            clarification_facts=state.get("clarification_facts"),
            clarification_history=state.get("clarification_history"),
            effective_personalization_context=state.get(
                "effective_personalization_context"
            ),
            available_theme_templates=state.get("available_theme_templates"),
            personalization_core_complete=state.get(
                "personalization_core_complete"
            ),
            missing_core_personalization_keys=state.get(
                "missing_core_personalization_keys"
            ),
            ambiguous_personalization_keys=state.get(
                "ambiguous_personalization_keys"
            ),
            additional_blocking_missing_information=state.get(
                "additional_blocking_missing_information"
            ),
        )
        return {
            "current_step": "blueprint",
            "status": WORKFLOW_STATUS_PROCESSING,
            "route_decision": "generate",
            "blueprint": deepcopy(blueprint),
        }
    except Exception as exc:
        category = mark_failure_category(
            exc,
            (
                "blueprint_validation"
                if isinstance(exc, (AIBlueprintValidationError, ValueError))
                else "internal_error"
            ),
        )
        logger.exception(
            GENERATION_FAILURE_LOG_MESSAGE,
            safe_identity_for_log(state.get("store_id")),
            safe_identity_for_log(state.get("tenant_id")),
            "blueprint",
            category,
            safe_exception_class_name(exc),
            exc_info=safe_exception_info(exc),
        )
        return _safe_blueprint_failure_update()


def _validate_blueprint_entry_state(state: AIStoreAgentState) -> None:
    if state.get("understanding_valid") is not True:
        raise ValueError("Blueprint requires valid understanding output.")
    if state.get("description_sufficient") is not True:
        raise ValueError("Blueprint requires sufficient personalization context.")
    if state.get("personalization_core_complete") is not True:
        raise ValueError("Blueprint requires all core personalization facts.")
    if state.get("missing_core_personalization_keys") != []:
        raise ValueError("Blueprint cannot run with missing core facts.")
    if state.get("ambiguous_personalization_keys") != []:
        raise ValueError("Blueprint cannot run with ambiguous core facts.")
    if state.get("additional_blocking_missing_information") != []:
        raise ValueError("Blueprint cannot run while blocking information remains.")


def _safe_blueprint_failure_update() -> dict[str, Any]:
    return {
        "current_step": "blueprint",
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "mode": "failed_recoverable",
        "route_decision": "failed_recoverable",
        "draft_payload": {},
        "clarification_questions": [],
        "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
        "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
    }


__all__ = ["blueprint_node"]
