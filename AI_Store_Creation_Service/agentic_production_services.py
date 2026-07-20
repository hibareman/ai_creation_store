"""Production bridge for agentic AI Store Creation service integration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django.core.exceptions import ValidationError

from .agentic.merging import (
    AIMergeValidationError,
    validate_clarification_answer_submission,
)
from .agentic.personalization import CORE_PERSONALIZATION_KEYS
from .agentic_session_services import (
    approve_cached_agentic_workflow,
    get_cached_agentic_workflow,
    resume_cached_agentic_workflow,
    start_cached_agentic_workflow,
)
from .agentic_state_store import save_agentic_workflow_state
from .draft_store import (
    delete_ai_draft,
    delete_ai_draft_meta,
    get_ai_draft,
    get_ai_draft_meta,
    save_ai_draft,
    save_ai_draft_meta,
)
from .constants import (
    AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE,
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
    regenerate_store_draft as regenerate_validated_store_draft,
    regenerate_store_draft_section as regenerate_validated_store_draft_section,
)


_PUBLIC_RESPONSE_KEYS = {"store_id", "draft_payload", "draft_metadata", "feedback", "ai_changes"}
_PUBLIC_DRAFT_KEYS = {
    "regeneration_summary",
    "store",
    "store_settings",
    "theme",
    "categories",
    "products",
    "clarification_needed",
    "clarification_questions",
    "error_code",
    "user_message",
    "retry_allowed",
    "manual_edit_allowed",
}
_PUBLIC_OBJECT_FIELDS = {
    "store": ("name", "description"),
    "store_settings": ("currency", "language", "timezone"),
    "theme": (
        "theme_template", "primary_color", "secondary_color", "font_family",
        "logo_url", "banner_url",
    ),
}
_PUBLIC_CATEGORY_FIELDS = ("name",)
_PUBLIC_PRODUCT_FIELDS = (
    "name", "description", "price", "sku", "category_name",
    "stock_quantity", "image_url",
)
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
    "target_audience",
    "product_direction",
    "blocking_missing_information",
    "missing_information",
    "confidence_score",
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

    try:
        canonical_answers = validate_clarification_answer_submission(
            clarification_questions=state.get("clarification_questions"),
            clarification_answers=clarification_answers,
        )
    except AIMergeValidationError as exc:
        raise ValidationError(AGENTIC_CLARIFICATION_INVALID_USER_MESSAGE) from exc

    resumed_state = resume_cached_agentic_workflow(
        store_id=state["store_id"],
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        clarification_answers=canonical_answers,
    )
    return _project_agentic_state_to_public_response(resumed_state)["draft_payload"]




def regenerate_current_agentic_ai_draft(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """Regenerate a cached ready-for-review Agentic draft and persist it atomically."""
    state = get_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    if state is None:
        raise ValidationError("No active agentic AI session found for this store")
    if (
        state.get("status") != WORKFLOW_STATUS_READY_FOR_REVIEW
        or state.get("mode") != "draft_ready"
        or state.get("route_decision") != "human_review"
        or not isinstance(state.get("draft_payload"), dict)
    ):
        raise ValidationError(
            "Full regeneration is allowed only when current workflow state is ready_for_review"
        )

    store = _get_authorized_store_or_raise(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    user_id = _authenticated_user_id_or_raise(user)
    previous_draft = get_ai_draft(store.id)
    previous_meta = get_ai_draft_meta(store.id)

    bridge_meta = {
        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "current_step": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "mode": "draft_ready",
        "is_fallback": False,
        "workflow_engine": "agentic",
        "original_user_store_description": state.get("user_store_description")
        or state.get("normalized_description"),
        "clarification_history": state.get("clarification_history", []),
        "clarification_facts": state.get("clarification_facts", {}),
        "latest_clarification_input": state.get("clarification_answers"),
        "blueprint": state.get("blueprint", {}),
        "confirmed_personalization_context": state.get(
            "confirmed_personalization_context", {}
        ),
        "effective_personalization_context": state.get(
            "effective_personalization_context", {}
        ),
        "clarification_round_count": state.get("clarification_round_count", 0),
        "repair_attempt_count": state.get("repair_attempt_count", 0),
    }

    try:
        save_ai_draft(store.id, state["draft_payload"])
        save_ai_draft_meta(store.id, bridge_meta)
        regenerated = regenerate_validated_store_draft(
            store_id=store.id,
            user=user,
            tenant_id=store.tenant_id,
        )
        ai_changes = _build_partial_regeneration_ai_changes(
            target_section=target_section,
            previous_draft=state["draft_payload"],
            regenerated_draft=regenerated,
            user_instruction=user_instruction,
        )
        updated_state = {
            **state,
            "draft_payload": regenerated,
            "ai_changes": ai_changes,
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "mode": "draft_ready",
            "route_decision": "human_review",
            "clarification_needed": False,
            "clarification_questions": [],
            "validation_errors": [],
            "review_approved": False,
            "application_success": False,
            "regeneration_summary": regenerated.get("regeneration_summary"),
        }
        save_agentic_workflow_state(
            tenant_id=store.tenant_id,
            store_id=store.id,
            user_id=user_id,
            state=updated_state,
        )
    finally:
        if previous_draft is None:
            delete_ai_draft(store.id)
        else:
            save_ai_draft(store.id, previous_draft)
        if previous_meta is None:
            delete_ai_draft_meta(store.id)
        else:
            save_ai_draft_meta(store.id, previous_meta)

    return _project_agentic_state_to_public_response(updated_state)


def regenerate_current_agentic_ai_draft_section(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
    target_section: str,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    """Regenerate one section of a cached ready-for-review Agentic draft."""
    state = get_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    if state is None:
        raise ValidationError("No active agentic AI session found for this store")
    if (
        state.get("status") != WORKFLOW_STATUS_READY_FOR_REVIEW
        or state.get("mode") != "draft_ready"
        or state.get("route_decision") != "human_review"
        or not isinstance(state.get("draft_payload"), dict)
    ):
        raise ValidationError(
            "Partial regeneration is allowed only when current workflow state is ready_for_review"
        )

    store = _get_authorized_store_or_raise(
        store_id=store_id, user=user, tenant_id=tenant_id
    )
    user_id = _authenticated_user_id_or_raise(user)
    previous_draft = get_ai_draft(store.id)
    previous_meta = get_ai_draft_meta(store.id)

    bridge_meta = {
        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "current_step": WORKFLOW_STATUS_READY_FOR_REVIEW,
        "mode": "draft_ready",
        "is_fallback": False,
        "workflow_engine": "agentic",
        "original_user_store_description": state.get("user_store_description")
        or state.get("normalized_description"),
        "clarification_history": state.get("clarification_history", []),
        "clarification_facts": state.get("clarification_facts", {}),
        "latest_clarification_input": state.get("clarification_answers"),
        "blueprint": state.get("blueprint", {}),
        "confirmed_personalization_context": state.get(
            "confirmed_personalization_context", {}
        ),
        "effective_personalization_context": state.get(
            "effective_personalization_context", {}
        ),
        "clarification_round_count": state.get("clarification_round_count", 0),
        "repair_attempt_count": state.get("repair_attempt_count", 0),
    }

    try:
        save_ai_draft(store.id, state["draft_payload"])
        save_ai_draft_meta(store.id, bridge_meta)
        regenerated = regenerate_validated_store_draft_section(
            store_id=store.id,
            user=user,
            tenant_id=store.tenant_id,
            target_section=target_section,
            user_instruction=user_instruction,
        )
        operation_meta = get_ai_draft_meta(store.id) or {}
        updated_state = {
            **state,
            "draft_payload": regenerated,
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "mode": "draft_ready",
            "route_decision": "human_review",
            "clarification_needed": False,
            "clarification_questions": [],
            "validation_errors": [],
            "review_approved": False,
            "application_success": False,
            "target_section": target_section,
            "last_partial_regeneration_target_section": target_section,
            "last_operation": operation_meta.get("last_operation", "partial_regeneration"),
            "last_operation_status": operation_meta.get("last_operation_status", "completed"),
        }
        save_agentic_workflow_state(
            tenant_id=store.tenant_id,
            store_id=store.id,
            user_id=user_id,
            state=updated_state,
        )
    finally:
        if previous_draft is None:
            delete_ai_draft(store.id)
        else:
            save_ai_draft(store.id, previous_draft)
        if previous_meta is None:
            delete_ai_draft_meta(store.id)
        else:
            save_ai_draft_meta(store.id, previous_meta)

    return _project_agentic_state_to_public_response(updated_state)

def apply_current_agentic_ai_draft_to_store(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """Approve the current Agentic draft and execute its final Apply Store node."""
    store = _get_authorized_store_or_raise(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    user_id = _authenticated_user_id_or_raise(user)
    try:
        completed_state = approve_cached_agentic_workflow(
            store_id=store.id,
            tenant_id=store.tenant_id,
            user_id=user_id,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    return {
        "store_id": completed_state["store_id"],
        "status": completed_state["status"],
        "current_step": completed_state["current_step"],
        "mode": completed_state["mode"],
        "is_fallback": False,
        "application_success": completed_state["application_success"],
        "created_categories_count": completed_state["created_categories_count"],
        "created_products_count": completed_state["created_products_count"],
        "completed_at": completed_state["completed_at"],
    }

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



def _build_partial_regeneration_ai_changes(
    *,
    target_section: str,
    previous_draft: Mapping[str, Any],
    regenerated_draft: Mapping[str, Any],
    user_instruction: str | None,
) -> dict[str, Any]:
    """Describe only the material changes made by partial regeneration."""
    details: list[str] = []

    if target_section == "theme":
        old_theme = previous_draft.get("theme") if isinstance(previous_draft.get("theme"), Mapping) else {}
        new_theme = regenerated_draft.get("theme") if isinstance(regenerated_draft.get("theme"), Mapping) else {}
        labels = {
            "theme_template": "قالب الثيم",
            "primary_color": "اللون الأساسي",
            "secondary_color": "اللون الثانوي",
            "font_family": "نوع الخط",
            "logo_url": "رابط الشعار",
            "banner_url": "رابط الغلاف",
        }
        for field, label in labels.items():
            old_value = old_theme.get(field)
            new_value = new_theme.get(field)
            if old_value != new_value:
                details.append(f"تم تغيير {label} من {old_value or 'فارغ'} إلى {new_value or 'فارغ'}.")
        summary = "تم تحديث الهوية البصرية للمتجر مع الحفاظ على بقية بيانات المسودة دون تغيير."

    elif target_section == "categories":
        old_categories = [item.get("name") for item in previous_draft.get("categories", []) if isinstance(item, Mapping)]
        new_categories = [item.get("name") for item in regenerated_draft.get("categories", []) if isinstance(item, Mapping)]
        old_products = [item.get("name") for item in previous_draft.get("products", []) if isinstance(item, Mapping)]
        new_products = [item.get("name") for item in regenerated_draft.get("products", []) if isinstance(item, Mapping)]
        details.append(f"تم استبدال الفئات: {', '.join(filter(None, old_categories)) or 'لا توجد'} ← {', '.join(filter(None, new_categories)) or 'لا توجد'}.")
        details.append(f"تمت إعادة توليد {len(new_products)} منتجات لتتوافق مع الفئات الجديدة بدلًا من {len(old_products)} منتجات سابقة.")
        summary = "تم تحديث الفئات وإعادة توليد المنتجات المرتبطة بها للحفاظ على اتساق الكتالوج."

    else:
        old_products = [item.get("name") for item in previous_draft.get("products", []) if isinstance(item, Mapping)]
        new_products = [item.get("name") for item in regenerated_draft.get("products", []) if isinstance(item, Mapping)]
        details.append(f"تم استبدال المنتجات السابقة ({len(old_products)}) بـ {len(new_products)} منتجات جديدة.")
        if new_products:
            details.append(f"المنتجات الجديدة: {', '.join(filter(None, new_products))}.")
        summary = "تم تحديث قائمة المنتجات مع الإبقاء على الفئات وبقية إعدادات المتجر كما هي."

    result: dict[str, Any] = {
        "target_section": target_section,
        "summary": summary,
        "details": details,
    }
    normalized_instruction = (user_instruction or "").strip()
    if normalized_instruction:
        result["user_instruction"] = normalized_instruction
    return result

def _project_draft_state(
    *,
    state: Mapping[str, Any],
    clarification_needed: bool,
    clarification_questions: Any,
) -> dict[str, Any]:
    draft_payload = state.get("draft_payload")
    if not isinstance(draft_payload, Mapping):
        return _project_failure_state(state)

    projected_payload = _project_public_draft_payload(draft_payload)
    projected_payload["clarification_needed"] = clarification_needed
    projected_payload["clarification_questions"] = _safe_question_list(
        clarification_questions
    )
    if clarification_needed and not projected_payload["clarification_questions"]:
        return _project_failure_state(state)

    response: dict[str, Any] = {
        "store_id": state.get("store_id"),
        "draft_payload": projected_payload,
        "draft_metadata": _project_metadata(state),
    }
    feedback = _safe_feedback(state.get("feedback"))
    if feedback is not None:
        response["feedback"] = feedback
    ai_changes = state.get("ai_changes")
    if isinstance(ai_changes, Mapping):
        response["ai_changes"] = deepcopy(dict(ai_changes))
    return _json_defensive_copy(response)


def _project_failure_state(state: Mapping[str, Any]) -> dict[str, Any]:
    error_code = _safe_text(
        state.get("error_code"),
        default=RECOVERABLE_FAILURE_ERROR_CODE,
    )
    user_message = _safe_text(
        state.get("user_message"),
        default=RECOVERABLE_FAILURE_USER_MESSAGE,
    )
    failure_state = {
        **dict(state),
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "current_step": "recoverable_failure",
        "mode": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "is_fallback": True,
        "error_code": error_code,
        "user_message": user_message,
    }
    response: dict[str, Any] = {
        "store_id": state.get("store_id"),
        "draft_payload": build_ai_recoverable_failure_payload(
            error_code=error_code,
            user_message=user_message,
        ),
        "draft_metadata": _project_metadata(failure_state),
    }
    feedback = _safe_feedback(state.get("feedback"))
    if feedback is not None:
        response["feedback"] = feedback
    return _json_defensive_copy(response)


def _project_metadata(state: Mapping[str, Any]) -> dict[str, Any]:
    status = _safe_text(
        state.get("status"),
        default=WORKFLOW_STATUS_FAILED_RECOVERABLE,
    )
    feedback = _safe_feedback(state.get("feedback"))
    current_step = _safe_text(
        state.get("current_step"),
        default=("recoverable_failure" if status == WORKFLOW_STATUS_FAILED_RECOVERABLE else "human_review"),
    )
    metadata: dict[str, Any] = {
        "status": status,
        "current_step": current_step,
        "mode": _safe_text(state.get("mode"), default=status),
        "is_fallback": status == WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "clarification_round_count": _safe_counter(
            state.get("clarification_round_count")
        ),
        "repair_attempt_count": _safe_counter(state.get("repair_attempt_count")),
        "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
        "workflow_engine": "agentic",
        "personalization_progress": _safe_personalization_progress(
            state.get("personalization_progress")
        ),
        "feedback": feedback,
        "validation_errors": _safe_validation_errors(state.get("validation_errors")),
        "application_success": state.get("application_success") is True,
        "review_required": status == WORKFLOW_STATUS_READY_FOR_REVIEW,
    }
    target_section = state.get("target_section") or state.get("last_partial_regeneration_target_section")
    if isinstance(target_section, str) and target_section.strip():
        metadata["target_section"] = target_section.strip()
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



def _safe_validation_errors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for issue in value:
        if not isinstance(issue, Mapping):
            continue
        path = issue.get("path")
        code = issue.get("code")
        message = issue.get("message")
        repairable = issue.get("repairable")
        if (
            isinstance(path, str) and path.strip()
            and isinstance(code, str) and code.strip()
            and isinstance(message, str) and message.strip()
            and isinstance(repairable, bool)
        ):
            safe.append({
                "path": path, "code": code,
                "message": message, "repairable": repairable,
            })
    return safe


def _safe_feedback(value: Any) -> dict[str, Any] | None:
    """Return the latest valid workflow Feedback without recalculating it."""
    from .agentic.feedback import validate_feedback_contract

    if value is None:
        return None
    try:
        return validate_feedback_contract(value)
    except (TypeError, ValueError):
        return None


def _safe_personalization_progress(value: Any) -> dict[str, Any]:
    total = len(CORE_PERSONALIZATION_KEYS)
    fallback = {
        "resolved_core_count": 0,
        "total_core_count": total,
        "core_complete": False,
        "missing_core_keys": list(CORE_PERSONALIZATION_KEYS),
    }
    if not isinstance(value, Mapping):
        return fallback
    resolved = value.get("resolved_core_count")
    reported_total = value.get("total_core_count")
    complete = value.get("core_complete")
    missing = value.get("missing_core_keys")
    if (
        isinstance(resolved, bool)
        or not isinstance(resolved, int)
        or resolved < 0
        or resolved > total
        or reported_total != total
        or not isinstance(complete, bool)
        or not isinstance(missing, list)
        or any(key not in CORE_PERSONALIZATION_KEYS for key in missing)
        or len(set(missing)) != len(missing)
        or missing != [key for key in CORE_PERSONALIZATION_KEYS if key in missing]
        or resolved + len(missing) != total
        or complete != (resolved == total)
    ):
        return fallback
    return {
        "resolved_core_count": resolved,
        "total_core_count": total,
        "core_complete": complete,
        "missing_core_keys": list(missing),
    }


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
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        return []
    safe_questions: list[dict[str, Any]] = []
    for question in value:
        if not isinstance(question, Mapping):
            return []
        question_key = question.get("question_key")
        question_text = question.get("question_text")
        options = question.get("options")
        other_option = question.get("other_option")
        if (
            not isinstance(question_key, str)
            or not question_key.strip()
            or not isinstance(question_text, str)
            or not question_text.strip()
            or not isinstance(options, list)
            or not options
            or any(not isinstance(option, str) or not option.strip() for option in options)
            or (other_option is not None and not isinstance(other_option, str))
        ):
            return []
        safe_question = {
            "question_key": question_key,
            "question_text": question_text,
            "options": list(options),
        }
        if isinstance(other_option, str) and other_option.strip():
            safe_question["other_option"] = other_option
        safe_questions.append(safe_question)
    return _json_defensive_copy(safe_questions)


def _project_public_draft_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    summary = value.get("regeneration_summary")
    if isinstance(summary, Mapping):
        payload["regeneration_summary"] = _json_defensive_copy(dict(summary))
    for section, fields in _PUBLIC_OBJECT_FIELDS.items():
        source = value.get(section)
        payload[section] = (
            {field: deepcopy(source[field]) for field in fields if field in source}
            if isinstance(source, Mapping)
            else {}
        )
    payload["categories"] = _project_public_item_list(
        value.get("categories"), _PUBLIC_CATEGORY_FIELDS
    )
    payload["products"] = _project_public_item_list(
        value.get("products"), _PUBLIC_PRODUCT_FIELDS
    )
    for field in (
        "clarification_needed", "error_code", "user_message",
        "retry_allowed", "manual_edit_allowed",
    ):
        if field in value:
            payload[field] = deepcopy(value[field])
    payload["clarification_questions"] = _safe_question_list(
        value.get("clarification_questions")
    ) if value.get("clarification_needed") is True else []
    return {
        key: _json_defensive_copy(payload[key])
        for key in _PUBLIC_DRAFT_KEYS
        if key in payload
    }


def _project_public_item_list(value: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {field: deepcopy(item[field]) for field in fields if field in item}
        for item in value
        if isinstance(item, Mapping)
    ]


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(deepcopy(value), ensure_ascii=False, allow_nan=False))


__all__ = [
    "get_current_agentic_ai_draft",
    "get_existing_agentic_session",
    "has_existing_agentic_session",
    "process_agentic_clarification_round",
    "regenerate_current_agentic_ai_draft",
    "regenerate_current_agentic_ai_draft_section",
    "start_agentic_ai_draft_workflow",
]
