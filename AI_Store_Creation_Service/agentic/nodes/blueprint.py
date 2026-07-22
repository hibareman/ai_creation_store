"""Provider-backed Blueprint node with validation and bounded AI repair."""
from __future__ import annotations
import logging
from copy import deepcopy
from typing import Any
from ...constants import RECOVERABLE_FAILURE_ERROR_CODE, RECOVERABLE_FAILURE_USER_MESSAGE, WORKFLOW_STATUS_FAILED_RECOVERABLE, WORKFLOW_STATUS_PROCESSING
from ..blueprinting import AIBlueprintValidationError, generate_ai_store_blueprint
from ..state import AIStoreAgentState
logger=logging.getLogger(__name__)

def blueprint_node(state: AIStoreAgentState) -> dict[str, Any]:
    try:
        _validate_blueprint_entry_state(state)
        blueprint, attempts = generate_ai_store_blueprint(
            tenant_id=state["tenant_id"], store_id=state["store_id"],
            normalized_description=state["normalized_description"],
            effective_personalization_context=state["effective_personalization_context"],
            clarification_history=state.get("clarification_history", []),
            available_theme_templates=state["available_theme_templates"],
            max_repair_attempts=3,
        )
        return {"current_step":"blueprint","status":WORKFLOW_STATUS_PROCESSING,
                "route_decision":"generate","blueprint":deepcopy(blueprint),
                "repair_attempt_count":attempts,"validation_errors":[]}
    except Exception as exc:
        logger.exception("AI Blueprint generation failed | store_id=%s | tenant_id=%s", state.get("store_id"), state.get("tenant_id"))
        repair_attempt_count = getattr(exc, "repair_attempt_count", state.get("repair_attempt_count", 0))
        return {"current_step":"blueprint","status":WORKFLOW_STATUS_FAILED_RECOVERABLE,
                "mode":"failed_recoverable","route_decision":"failed_recoverable",
                "draft_payload":{},"clarification_questions":[],
                "repair_attempt_count":repair_attempt_count,
                "validation_errors":[{"path":"$","code":"blueprint_failed","message":str(exc),"repairable":False}],
                "error_code":RECOVERABLE_FAILURE_ERROR_CODE,"user_message":RECOVERABLE_FAILURE_USER_MESSAGE}

def _validate_blueprint_entry_state(state: AIStoreAgentState) -> None:
    if state.get("understanding_valid") is not True or state.get("description_sufficient") is not True:
        raise ValueError("Blueprint requires valid and sufficient understanding output.")
    if state.get("personalization_core_complete") is not True:
        raise ValueError("Blueprint requires complete personalization.")
    for key in ("missing_core_personalization_keys","ambiguous_personalization_keys","additional_blocking_missing_information"):
        if state.get(key) != []:
            raise ValueError(f"Blueprint cannot run while {key} is non-empty.")
    if not isinstance(state.get("effective_personalization_context"), dict):
        raise ValueError("Blueprint requires effective_personalization_context.")
    if not isinstance(state.get("available_theme_templates"), list) or not state.get("available_theme_templates"):
        raise ValueError("Blueprint requires available theme templates.")

__all__=["blueprint_node"]
