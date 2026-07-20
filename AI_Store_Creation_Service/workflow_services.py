"""
Service-layer helpers for AI Store Creation workflow.

This module is intentionally limited to focused workflow services.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Mapping

from django.core.exceptions import ValidationError

from stores.models import Store

from .draft_store import (
    get_ai_draft,
    get_ai_draft_meta,
    save_ai_draft,
    save_ai_draft_meta,
)
from .audit_services import _write_ai_audit_log
from .metadata_services import (
    _build_recoverable_failure_metadata,
    _build_recoverable_fallback_metadata,
    _get_or_rebuild_draft_metadata,
    _recoverable_error_code_for_exception,
    _safe_non_negative_int,
    _with_workflow_counter_metadata,
    is_legacy_clarification_fallback,
)
from .normalization import (
    _apply_targeted_prevalidation_repairs,
    _ensure_theme_template_is_available,
)
from .constants import (
    LAST_OPERATION_PARTIAL_REGENERATION,
    LAST_OPERATION_STATUS_COMPLETED,
    PARTIAL_REGENERATION_FAILED_ERROR_CODE,
    PARTIAL_REGENERATION_FAILED_USER_MESSAGE,
    READY_FOR_REVIEW_WORKFLOW_STATUSES,
    RECOVERABLE_FAILURE_ERROR_CODE,
    THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE,
    THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
)
from .exceptions import AIDraftSchemaValidationError, AIProviderParsingError
from .parsers import parse_provider_raw_response_to_dict
from .providers import get_ai_provider_client
from .selectors import (
    get_available_theme_template_names,
    get_store_for_ai_flow,
)
from .validators import (
    build_ai_recoverable_failure_payload,
    detect_ai_response_mode,
    validate_initial_description,
    validate_basic_draft_schema,
    validate_categories_section,
    validate_products_section,
    validate_regenerated_draft_schema,
    validate_store_section,
    validate_store_settings_section,
    validate_theme_section,
)


logger = logging.getLogger(__name__)
_ALLOWED_PARTIAL_TARGET_SECTIONS = {"theme", "categories", "products"}
_ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")
_EXPLICIT_STORE_NAME_PATTERNS = [
    re.compile(
        r"(?:store\s+name\s+is|named|called)\s*[:\-]?\s*[\"'“”‘’«»]?(?P<name>[^\n\r\"'“”‘’«»،,.;:]{2,80})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:اسم\s+المتجر(?:\s+هو)?|المتجر\s+اسمه|متجر(?:ي)?\s+باسم)\s*[:\-]?\s*[\"'“”‘’«»]?(?P<name>[^\n\r\"'“”‘’«»،,.;:]{2,80})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?:name|اسم)\s*[:\-]\s*[\"'“”‘’«»]?(?P<name>[^\n\r\"'“”‘’«»،,.;:]{2,80})",
        flags=re.IGNORECASE,
    ),
]
_HEURISTIC_STORE_NAME_KEYWORDS = [
    (
        (
            "skincare",
            "skin care",
            "beauty",
            "cosmetic",
            "cosmetics",
            "perfume",
            "perfumes",
            "fragrance",
            "fragrances",
            "عناية بالبشرة",
            "بشرة",
            "تجميل",
            "مكياج",
            "عطور",
            "عطر",
        ),
        "Beauty Store",
        "متجر الجمال",
    ),
    (
        ("fashion", "clothing", "apparel", "ملابس", "أزياء", "ازياء", "موضة"),
        "Fashion Store",
        "متجر الأزياء",
    ),
    (
        ("electronics", "gadgets", "devices", "إلكترونيات", "الكترونيات", "أجهزة", "اجهزة"),
        "Electronics Store",
        "متجر الإلكترونيات",
    ),
    (
        ("coffee", "cafe", "caf\u00e9", "قهوة", "كافيه", "مقهى", "مقهي"),
        "Coffee Store",
        "متجر القهوة",
    ),
    (
        ("jewelry", "jewellery", "مجوهرات", "ذهب"),
        "Jewelry Store",
        "متجر المجوهرات",
    ),
]
def _parse_provider_response_with_single_retry(
    *,
    provider_call: Callable[[], dict[str, Any]],
    action: str,
    store_id: int,
) -> dict[str, Any]:
    """
    Parse provider response with one automatic retry on parse-only failures.

    This keeps behavior safe for small local models that occasionally return
    malformed JSON on first attempt.
    """
    raw_response = provider_call()
    try:
        return parse_provider_raw_response_to_dict(raw_response)
    except AIProviderParsingError as first_exc:
        logger.warning(
            "Provider parse failed on first attempt; retrying once. action=%s, store_id=%s, reason=%s",
            action,
            store_id,
            str(first_exc),
        )
        raw_response_retry = provider_call()
        return parse_provider_raw_response_to_dict(raw_response_retry)


def _extract_partial_section_replacement(
    payload: dict[str, Any],
    target_section: str,
) -> Any:
    """Extract the replacement payload for one partial-regeneration target."""
    if not isinstance(payload, dict):
        raise AIDraftSchemaValidationError(
            "Partial regeneration payload must be a JSON object."
        )

    if target_section == "categories":
        expected_keys = {"categories", "products"}
        if set(payload.keys()) != expected_keys:
            raise AIDraftSchemaValidationError(
                "Categories regeneration must return exactly categories and products."
            )
        return {
            "categories": payload["categories"],
            "products": payload["products"],
        }

    if target_section not in payload:
        raise AIDraftSchemaValidationError(
            f"Partial regeneration payload must include top-level key '{target_section}'."
        )
    if set(payload.keys()) != {target_section}:
        raise AIDraftSchemaValidationError(
            "Partial regeneration payload must include only the requested section key."
        )
    return payload[target_section]


def _clean_store_name_candidate(candidate: str) -> str:
    normalized = " ".join(str(candidate or "").strip().split())
    normalized = normalized.strip(" \t\n\r-–—:;,.!?؟،'\"“”‘’«»()[]{}")
    normalized = " ".join(normalized.split())
    if len(normalized) > 80:
        normalized = normalized[:80].rstrip()
    return normalized


def derive_store_name_from_description(user_description: str) -> str:
    """
    Derive a safe deterministic initial store name from user description.

    This helper is intentionally local and provider-independent.
    """
    if not isinstance(user_description, str) or not user_description.strip():
        raise ValidationError("user_store_description is required")

    normalized_description = " ".join(user_description.strip().split())
    normalized_lower = normalized_description.casefold()
    has_arabic_text = bool(_ARABIC_CHAR_RE.search(normalized_description))

    for pattern in _EXPLICIT_STORE_NAME_PATTERNS:
        match = pattern.search(normalized_description)
        if not match:
            continue
        extracted_name = _clean_store_name_candidate(match.group("name"))
        if extracted_name:
            return extracted_name

    for keywords, english_name, arabic_name in _HEURISTIC_STORE_NAME_KEYWORDS:
        if any(keyword.casefold() in normalized_lower for keyword in keywords):
            candidate_name = arabic_name if has_arabic_text else english_name
            cleaned = _clean_store_name_candidate(candidate_name)
            if cleaned:
                return cleaned

    fallback_name = "متجري" if has_arabic_text else "My Store"
    cleaned_fallback = _clean_store_name_candidate(fallback_name)
    return cleaned_fallback or "My Store"




def create_draft_store_for_ai_flow(
    user,
    tenant_id: int | None,
    *,
    name: str,
    description: str = "",
) -> Store:
    """
    Create a real Store record immediately for AI workflow with status='draft'.

    Security/alignment checks:
    - authenticated user is required
    - trusted tenant context is required
    - user tenant context must match trusted tenant context
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Store name is required")

    if not isinstance(description, str):
        raise ValidationError("Store description must be a string")

    store = Store.objects.create(
        owner=user,
        tenant_id=normalized_tenant_id,
        name=name.strip(),
        description=description,
        status="draft",
    )

    logger.info(
        "AI draft store created: store_id=%s, owner_id=%s, tenant_id=%s",
        store.id,
        user.id,
        normalized_tenant_id,
    )
    return store


def start_ai_draft_workflow(
    *,
    user,
    tenant_id: int | None,
    user_store_description: str,
) -> dict[str, Any]:
    """
    Start draft flow end-to-end with locally derived initial store name.

    Flow:
    1) normalize and validate user description
    2) derive deterministic initial store name locally (no provider dependency)
    3) create draft store
    4) generate initial AI draft
    5) return current draft state
    """
    normalized_description = validate_initial_description(user_store_description)
    derived_store_name = derive_store_name_from_description(normalized_description)

    store = create_draft_store_for_ai_flow(
        user=user,
        tenant_id=tenant_id,
        name=derived_store_name,
        description="",
    )
    generate_initial_store_draft(
        store_id=store.id,
        user=user,
        tenant_id=tenant_id,
        user_store_description=normalized_description,
    )
    return get_current_ai_draft(
        store_id=store.id,
        user=user,
        tenant_id=tenant_id,
    )


def generate_initial_store_draft(
    store_id: int,
    user,
    tenant_id: int | None,
    user_store_description: str,
) -> dict[str, Any]:
    """
    Orchestrate initial AI draft generation for an already-created draft store.

    Flow:
    1) verify store access via trusted user + tenant selector
    2) fetch available theme template names
    3) call provider official generation path
    4) parse provider raw response
    5) run structural validators and mode detection
    6) save resulting draft + metadata to temporary storage
    7) on parsing/validation failure, save standardized recoverable failure payload
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    normalized_description = validate_initial_description(user_store_description)

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    _write_ai_audit_log(
        tenant_id=store.tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="start_draft",
        status="requested",
        message="Initial AI draft generation requested.",
    )

    available_theme_templates = get_available_theme_template_names()
    if not available_theme_templates:
        reason = "No available theme templates found."
        fallback_payload = build_ai_recoverable_failure_payload(
            error_code=THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE,
            user_message=THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE,
        )
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=reason,
                error_code=THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE,
                user_message=THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE,
                original_user_store_description=normalized_description,
                clarification_round_count=0,
                repair_attempt_count=0,
            ),
        )
        _write_ai_audit_log(
            tenant_id=store.tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="start_draft",
            status="failed",
            message=reason,
        )
        return fallback_payload

    save_ai_draft_meta(
        store.id,
        _with_workflow_counter_metadata(
            {
                "status": WORKFLOW_STATUS_PROCESSING,
                "current_step": "analyzing_description",
                "original_user_store_description": normalized_description,
                "is_fallback": False,
            }
        ),
    )

    try:
        provider = get_ai_provider_client()
        payload = _parse_provider_response_with_single_retry(
            provider_call=lambda: provider.generate_store_draft(
                tenant_id=store.tenant_id,
                store_id=store.id,
                user_store_description=normalized_description,
                available_theme_templates=available_theme_templates,
            ),
            action="start_draft",
            store_id=store.id,
        )
        payload = _apply_targeted_prevalidation_repairs(
            payload,
            available_theme_templates=available_theme_templates,
        )
        payload = validate_basic_draft_schema(payload)
        mode = detect_ai_response_mode(payload)

        if mode == "draft_ready":
            validate_store_section(payload["store"])
            validate_store_settings_section(payload["store_settings"])
            validate_theme_section(payload["theme"])
            _ensure_theme_template_is_available(
                payload["theme"],
                available_theme_templates,
            )
            validated_categories = validate_categories_section(payload["categories"])
            category_names = [item["name"] for item in validated_categories]
            validate_products_section(payload["products"], category_names)

        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            _with_workflow_counter_metadata(
                {
                    "status": (
                        WORKFLOW_STATUS_NEEDS_CLARIFICATION
                        if mode == "clarification"
                        else WORKFLOW_STATUS_READY_FOR_REVIEW
                    ),
                    "current_step": (
                        "analyzing_description"
                        if mode == "clarification"
                        else "setting_up_store_configuration"
                    ),
                    "mode": mode,
                    "is_fallback": False,
                    "original_user_store_description": normalized_description,
                }
            ),
        )
        _write_ai_audit_log(
            tenant_id=store.tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="start_draft",
            status="completed",
            message=f"Initial draft completed with mode '{mode}'.",
        )
        return payload
    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Initial AI draft generation failed; saving recoverable failure payload. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        error_code = _recoverable_error_code_for_exception(exc)
        fallback_payload = build_ai_recoverable_failure_payload(error_code=error_code)
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=str(exc),
                error_code=error_code,
                original_user_store_description=normalized_description,
            ),
        )
        _write_ai_audit_log(
            tenant_id=store.tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="start_draft",
            status="failed",
            message=str(exc),
        )
        return fallback_payload


def get_current_ai_draft(store_id: int, user, tenant_id: int | None) -> dict[str, Any]:
    """
    Retrieve the current temporary AI draft + metadata for an allowed store.

    This service may normalize legacy cached draft state into the current
    frontend-safe workflow contract.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    draft_payload = get_ai_draft(store.id)
    if draft_payload is None:
        raise ValidationError("No temporary AI draft found for this store")

    cached_draft_meta = get_ai_draft_meta(store.id)
    if is_legacy_clarification_fallback(draft_payload, cached_draft_meta or {}):
        draft_payload = build_ai_recoverable_failure_payload(
            error_code=RECOVERABLE_FAILURE_ERROR_CODE
        )
        save_ai_draft(store.id, draft_payload)

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=draft_payload,
        draft_meta=cached_draft_meta,
        rebuild_partial=False,
    )

    return {
        "store_id": store.id,
        "draft_payload": draft_payload,
        "draft_metadata": draft_meta,
    }


def process_clarification_round(
    store_id: int,
    user,
    tenant_id: int | None,
    clarification_answers: Any,
) -> dict[str, Any]:
    """
    Orchestrate one clarification round for temporary AI draft workflow.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    _write_ai_audit_log(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="clarification_round",
        status="requested",
        message="Clarification round requested.",
    )

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="No temporary AI draft found for this store.",
        )
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    current_status = draft_meta.get("status")
    if current_status != WORKFLOW_STATUS_NEEDS_CLARIFICATION:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="Current workflow state does not require clarification.",
        )
        raise ValidationError("Current workflow state does not require clarification")

    if not current_draft.get("clarification_needed", False):
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="Current draft is not in clarification mode.",
        )
        raise ValidationError("Current draft is not in clarification mode")

    original_description = draft_meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="Original user store description missing from metadata.",
        )
        raise ValidationError("Original user store description is missing from draft metadata")

    raw_round_count = draft_meta.get("clarification_round_count", 0)
    try:
        clarification_round_count = int(raw_round_count)
    except (TypeError, ValueError):
        clarification_round_count = 0

    repair_attempt_count = _safe_non_negative_int(
        draft_meta.get("repair_attempt_count"),
        0,
    )

    if clarification_round_count >= MAX_CLARIFICATION_ROUNDS:
        fallback_payload = build_ai_recoverable_failure_payload(
            error_code="clarification_limit_reached",
            user_message="The clarification limit was reached. You can retry or edit the draft manually.",
        )
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _with_workflow_counter_metadata(
                {
                    "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                    "current_step": "recoverable_failure",
                    "mode": "failed_recoverable",
                    "is_fallback": True,
                    "error_code": "clarification_limit_reached",
                    "user_message": "The clarification limit was reached. You can retry or edit the draft manually.",
                    "retry_allowed": True,
                    "manual_edit_allowed": True,
                    "original_user_store_description": original_description,
                    "clarification_history": (
                        draft_meta.get("clarification_history")
                        if isinstance(draft_meta.get("clarification_history"), list)
                        else []
                    ),
                },
                source_metadata=draft_meta,
                clarification_round_count=clarification_round_count,
                repair_attempt_count=repair_attempt_count,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="Clarification round limit reached.",
        )
        return fallback_payload
    if clarification_answers is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="clarification_answers is required.",
        )
        raise ValidationError("clarification_answers is required")

    if isinstance(clarification_answers, str):
        clarification_input = clarification_answers.strip()
    else:
        if clarification_answers in ({}, [], ()):
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="clarification_round",
                status="failed",
                message="clarification_answers is required.",
            )
            raise ValidationError("clarification_answers is required")
        clarification_input = json.dumps(clarification_answers, ensure_ascii=False)

    if not clarification_input or clarification_input in {"null", "{}", "[]", '""'}:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message="clarification_answers is required.",
        )
        raise ValidationError("clarification_answers is required")

    next_round_count = clarification_round_count + 1

    existing_history = (
        draft_meta.get("clarification_history")
        if isinstance(draft_meta.get("clarification_history"), list)
        else []
    )
    updated_history = [
        *existing_history,
        {
            "round": next_round_count,
            "clarification_input": clarification_input,
        },
    ]

    save_ai_draft_meta(
        store.id,
        _with_workflow_counter_metadata(
            {
                "status": WORKFLOW_STATUS_PROCESSING,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "original_user_store_description": original_description,
                "latest_clarification_input": clarification_input,
                "clarification_history": updated_history,
            },
            source_metadata=draft_meta,
            clarification_round_count=next_round_count,
            repair_attempt_count=repair_attempt_count,
        ),
    )

    try:
        provider = get_ai_provider_client()
        available_theme_templates = get_available_theme_template_names()
        payload = _parse_provider_response_with_single_retry(
            provider_call=lambda: provider.clarify_store_draft(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                current_draft=current_draft,
                prompt=clarification_input,
                context={
                    "original_store_description": original_description,
                    "clarification_round_count": next_round_count,
                    "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
                    "repair_attempt_count": repair_attempt_count,
                    "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                    "latest_clarification_input": clarification_input,
                    "clarification_history": updated_history,
                    "available_theme_templates": available_theme_templates,
                    "is_final_clarification_round": next_round_count >= MAX_CLARIFICATION_ROUNDS,
                },
            ),
            action="clarification_round",
            store_id=store.id,
        )
        payload = _apply_targeted_prevalidation_repairs(payload)
        payload = validate_basic_draft_schema(payload)
        mode = detect_ai_response_mode(payload)
        new_round_count = next_round_count

        if mode == "draft_ready":
            if not available_theme_templates:
                raise AIDraftSchemaValidationError("No available theme templates found")
            payload = _apply_targeted_prevalidation_repairs(
                payload,
                available_theme_templates=available_theme_templates,
            )
            validate_store_section(payload["store"])
            validate_store_settings_section(payload["store_settings"])
            validate_theme_section(payload["theme"])
            _ensure_theme_template_is_available(
                payload["theme"],
                available_theme_templates,
            )
            validated_categories = validate_categories_section(payload["categories"])
            category_names = [item["name"] for item in validated_categories]
            validate_products_section(payload["products"], category_names)

            save_ai_draft(store.id, payload)
            save_ai_draft_meta(
                store.id,
                _with_workflow_counter_metadata(
                    {
                        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                        "current_step": "setting_up_store_configuration",
                        "mode": "draft_ready",
                        "is_fallback": False,
                        "original_user_store_description": original_description,
                        "latest_clarification_input": clarification_input,
                        "clarification_history": updated_history,
                    },
                    source_metadata=draft_meta,
                    clarification_round_count=new_round_count,
                    repair_attempt_count=repair_attempt_count,
                ),
            )
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="clarification_round",
                status="completed",
                message="Clarification round completed with ready_for_review status.",
            )
            return payload

        if new_round_count >= MAX_CLARIFICATION_ROUNDS:
            if not available_theme_templates:
                raise AIDraftSchemaValidationError("No available theme templates found")

            final_context = {
                "clarification_round_count": new_round_count,
                "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
                "repair_attempt_count": repair_attempt_count,
                "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                "latest_clarification_input": clarification_input,
                "clarification_history": updated_history,
                "available_theme_templates": available_theme_templates,
                "is_final_clarification_round": True,
                "instruction": (
                    "The clarification round limit has been reached after the latest answer. "
                    "Do not ask more clarification questions. Generate the best complete "
                    "draft-ready payload now using all available information."
                ),
            }

            def _request_final_payload(extra_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
                context = dict(final_context)
                if extra_context:
                    context.update(extra_context)
                return _parse_provider_response_with_single_retry(
                    provider_call=lambda: provider.regenerate_store_draft(
                        tenant_id=normalized_tenant_id,
                        store_id=store.id,
                        original_store_description=original_description,
                        current_draft=current_draft,
                        clarification_context=context,
                        available_theme_templates=available_theme_templates,
                    ),
                    action="clarification_round_finalization",
                    store_id=store.id,
                )

            def _validate_final_payload(candidate_payload: dict[str, Any]) -> dict[str, Any]:
                candidate_payload = _apply_targeted_prevalidation_repairs(
                    candidate_payload,
                    available_theme_templates=available_theme_templates,
                )
                candidate_payload = validate_basic_draft_schema(candidate_payload)
                if detect_ai_response_mode(candidate_payload) != "draft_ready":
                    raise AIDraftSchemaValidationError(
                        "Final clarification round must return a draft-ready payload"
                    )
                validate_store_section(candidate_payload["store"])
                validate_store_settings_section(candidate_payload["store_settings"])
                validate_theme_section(candidate_payload["theme"])
                _ensure_theme_template_is_available(
                    candidate_payload["theme"],
                    available_theme_templates,
                )
                validated_categories = validate_categories_section(candidate_payload["categories"])
                category_names = [item["name"] for item in validated_categories]
                validate_products_section(candidate_payload["products"], category_names)
                return candidate_payload

            final_payload = _request_final_payload()
            try:
                final_payload = _validate_final_payload(final_payload)
            except AIDraftSchemaValidationError as final_exc:
                final_payload = _request_final_payload(
                    {
                        "previous_finalization_error": str(final_exc),
                        "previous_invalid_payload": final_payload,
                        "repair_instruction": (
                            "Your previous final-round response was invalid. "
                            "Return one complete draft-ready JSON object now. "
                            "Do not ask questions. Include 2 to 5 categories, "
                            "2 to 4 products, and a complete theme."
                        ),
                    }
                )
                final_payload = _validate_final_payload(final_payload)

            save_ai_draft(store.id, final_payload)
            save_ai_draft_meta(
                store.id,
                _with_workflow_counter_metadata(
                    {
                        "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                        "current_step": "setting_up_store_configuration",
                        "mode": "draft_ready",
                        "is_fallback": False,
                        "final_clarification_round": True,
                        "original_user_store_description": original_description,
                        "latest_clarification_input": clarification_input,
                        "clarification_history": updated_history,
                    },
                    source_metadata=draft_meta,
                    clarification_round_count=new_round_count,
                    repair_attempt_count=repair_attempt_count,
                ),
            )
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="clarification_round",
                status="completed",
                message="Final clarification round completed with ready_for_review status.",
            )
            return final_payload

        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            _with_workflow_counter_metadata(
                {
                    "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                    "current_step": "analyzing_description",
                    "mode": "clarification",
                    "is_fallback": False,
                    "original_user_store_description": original_description,
                    "latest_clarification_input": clarification_input,
                    "clarification_history": updated_history,
                },
                source_metadata=draft_meta,
                clarification_round_count=new_round_count,
                repair_attempt_count=repair_attempt_count,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="completed",
            message="Clarification round completed with clarification mode.",
        )
        return payload

    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Clarification round failed; saving recoverable failure payload. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        error_code = _recoverable_error_code_for_exception(exc)
        fallback_payload = build_ai_recoverable_failure_payload(error_code=error_code)
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=str(exc),
                error_code=error_code,
                original_user_store_description=original_description,
                clarification_round_count=next_round_count,
                repair_attempt_count=repair_attempt_count,
                latest_clarification_input=clarification_input,
                clarification_history=updated_history,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="clarification_round",
            status="failed",
            message=str(exc),
        )
        return fallback_payload


def regenerate_store_draft(
    store_id: int,
    user,
    tenant_id: int,
) -> dict[str, Any]:
    """Run strict full Agentic Regeneration and replace the review draft only after validation."""
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")
    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc
    if normalized_tenant_id <= 0 or getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")
    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")
    draft_meta = _get_or_rebuild_draft_metadata(
        store=store, draft_payload=current_draft, draft_meta=get_ai_draft_meta(store.id), rebuild_partial=True
    )
    if draft_meta.get("status") not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        raise ValidationError("Full regeneration is allowed only when current workflow state is ready_for_review")

    original_description = draft_meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
        raise ValidationError("Original user store description is missing from draft metadata")
    normalized_description = original_description.strip()
    available_theme_templates = get_available_theme_template_names()
    if not available_theme_templates:
        raise ValidationError("No available theme templates found")

    clarification_history = draft_meta.get("clarification_history") if isinstance(draft_meta.get("clarification_history"), list) else []
    clarification_context = {
        "clarification_history": clarification_history,
        "clarification_facts": draft_meta.get("clarification_facts", {}),
        "latest_clarification_input": draft_meta.get("latest_clarification_input"),
    }
    blueprint = draft_meta.get("blueprint") if isinstance(draft_meta.get("blueprint"), Mapping) else {}
    confirmed_context = draft_meta.get("confirmed_personalization_context")
    if not isinstance(confirmed_context, Mapping):
        confirmed_context = draft_meta.get("effective_personalization_context")
    if not isinstance(confirmed_context, Mapping):
        confirmed_context = {}

    clarification_round_count = _safe_non_negative_int(draft_meta.get("clarification_round_count"), 0)
    prior_repair_count = _safe_non_negative_int(draft_meta.get("repair_attempt_count"), 0)
    _write_ai_audit_log(tenant_id=normalized_tenant_id, store_id=store.id, actor_id=getattr(user, "id", None), action="full_regenerate", status="requested", message="Agentic full regeneration requested.")
    save_ai_draft_meta(store.id, _with_workflow_counter_metadata({
        **draft_meta, "status": WORKFLOW_STATUS_PROCESSING, "current_step": "regenerate",
        "mode": "processing", "is_fallback": False, "regeneration_in_progress": True,
    }, source_metadata=draft_meta, clarification_round_count=clarification_round_count, repair_attempt_count=prior_repair_count))

    provider = get_ai_provider_client()
    last_error: Exception | None = None
    candidate: dict[str, Any] | None = None
    last_invalid_payload: dict[str, Any] | None = None
    attempts_used = 0
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        attempts_used = attempt
        repair_context = dict(clarification_context)
        if last_error is not None:
            repair_context["regeneration_validation_error"] = str(last_error)
            repair_context["repair_attempt"] = attempt
            repair_context["repair_instruction"] = (
                "Repair the supplied invalid_regeneration_payload instead of creating another unrelated draft. "
                "Return the complete regeneration JSON contract only. Preserve all already-valid fields and "
                "change only what is required by the validation error. The regeneration_summary.message must "
                "contain 3 to 6 non-empty lines separated by newline characters. Categories must contain 2 to "
                "5 items. Products must contain 2 to 4 items, and every product category_name must match "
                "one of those category names exactly."
            )
            if last_invalid_payload is not None:
                repair_context["invalid_regeneration_payload"] = last_invalid_payload
        try:
            raw = provider.regenerate_store_draft(
                tenant_id=normalized_tenant_id, store_id=store.id,
                original_store_description=normalized_description, current_draft=current_draft,
                clarification_context=repair_context, available_theme_templates=available_theme_templates,
                blueprint=blueprint, confirmed_personalization_context=confirmed_context,
            )
            parsed = parse_provider_raw_response_to_dict(raw)
            if isinstance(parsed, Mapping):
                last_invalid_payload = dict(parsed)
            logger.debug(
                "Agentic regeneration provider response parsed (store_id=%s, tenant_id=%s, top_level_keys=%s)",
                store.id,
                normalized_tenant_id,
                sorted(parsed.keys()) if isinstance(parsed, Mapping) else type(parsed).__name__,
            )
            parsed = validate_regenerated_draft_schema(parsed)
            validate_store_section(parsed["store"])
            validate_store_settings_section(parsed["store_settings"])
            validate_theme_section(parsed["theme"])
            _ensure_theme_template_is_available(parsed["theme"], available_theme_templates)
            categories = validate_categories_section(parsed["categories"])
            validate_products_section(parsed["products"], [item["name"] for item in categories])
            candidate = parsed
            logger.info(
                "Agentic full regeneration validated successfully "
                "(store_id=%s, tenant_id=%s, attempt=%s/%s, categories=%s, products=%s)",
                store.id,
                normalized_tenant_id,
                attempt + 1,
                MAX_REPAIR_ATTEMPTS + 1,
                len(candidate.get("categories", [])),
                len(candidate.get("products", [])),
            )
            break
        except (AIProviderParsingError, AIDraftSchemaValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.exception(
                "Agentic full regeneration attempt failed validation or parsing "
                "(store_id=%s, tenant_id=%s, attempt=%s/%s)",
                store.id,
                normalized_tenant_id,
                attempt + 1,
                MAX_REPAIR_ATTEMPTS + 1,
            )
            continue
        except Exception as exc:
            last_error = exc
            logger.exception(
                "Unexpected Agentic full regeneration failure "
                "(store_id=%s, tenant_id=%s, attempt=%s/%s)",
                store.id,
                normalized_tenant_id,
                attempt + 1,
                MAX_REPAIR_ATTEMPTS + 1,
            )
            continue

    if candidate is None:
        logger.error(
            "Agentic full regeneration exhausted all attempts; preserving current draft "
            "(store_id=%s, tenant_id=%s, attempts=%s, final_error=%r)",
            store.id,
            normalized_tenant_id,
            MAX_REPAIR_ATTEMPTS + 1,
            last_error,
            exc_info=(type(last_error), last_error, last_error.__traceback__) if last_error is not None else None,
        )
        save_ai_draft_meta(store.id, _with_workflow_counter_metadata({
            **draft_meta, "status": WORKFLOW_STATUS_READY_FOR_REVIEW, "current_step": "human_review",
            "mode": "draft_ready", "is_fallback": False, "regeneration_in_progress": False,
            "last_operation": "full_regeneration", "last_operation_status": "failed",
            "last_operation_error_code": "regeneration_failed",
            "last_operation_user_message": "The store could not be regenerated. The current draft was preserved.",
        }, source_metadata=draft_meta, clarification_round_count=clarification_round_count, repair_attempt_count=prior_repair_count + attempts_used))
        _write_ai_audit_log(tenant_id=normalized_tenant_id, store_id=store.id, actor_id=getattr(user, "id", None), action="full_regenerate", status="failed", message=str(last_error or "Regeneration failed"))
        raise ValidationError("The store could not be regenerated. The current draft was preserved.")

    save_ai_draft(store.id, candidate)
    save_ai_draft_meta(store.id, _with_workflow_counter_metadata({
        **draft_meta, "status": WORKFLOW_STATUS_READY_FOR_REVIEW, "current_step": "human_review",
        "mode": "draft_ready", "is_fallback": False, "regeneration_in_progress": False,
        "last_operation": "full_regeneration", "last_operation_status": LAST_OPERATION_STATUS_COMPLETED,
        "regeneration_summary": candidate["regeneration_summary"],
    }, source_metadata=draft_meta, clarification_round_count=clarification_round_count, repair_attempt_count=prior_repair_count + attempts_used))
    _write_ai_audit_log(tenant_id=normalized_tenant_id, store_id=store.id, actor_id=getattr(user, "id", None), action="full_regenerate", status="completed", message="Agentic full regeneration completed and validated.")
    return candidate


def regenerate_store_draft_section(
    store_id: int,
    user,
    tenant_id: int | None,
    target_section: str,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    """
    Orchestrate partial draft regeneration for one supported section only.

    Supported target sections in MVP:
    - theme
    - categories
    - products

    Critical guarantees:
    - same store_id/user/tenant/session
    - no new free-text user prompt
    - do not overwrite current draft with fallback on failure
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    try:
        normalized_tenant_id = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid trusted tenant context") from exc

    if normalized_tenant_id <= 0:
        raise ValidationError("Invalid trusted tenant context")

    if getattr(user, "tenant_id", None) != normalized_tenant_id:
        raise ValidationError("User tenant context does not match trusted tenant context")

    if not isinstance(target_section, str):
        raise ValidationError("target_section is required")
    normalized_target_section = target_section.strip().lower()
    if normalized_target_section not in _ALLOWED_PARTIAL_TARGET_SECTIONS:
        raise ValidationError(
            "target_section must be one of: theme, categories, products"
        )

    normalized_user_instruction = None
    if user_instruction is not None:
        if not isinstance(user_instruction, str) or not user_instruction.strip():
            raise ValidationError("user_instruction must be a non-empty string when provided")
        normalized_user_instruction = user_instruction.strip()

    store = get_store_for_ai_flow(store_id=store_id, user=user, tenant_id=normalized_tenant_id)
    if not store:
        raise ValidationError("Store not found or access denied")

    _write_ai_audit_log(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="partial_regenerate",
        status="requested",
        message=f"Partial regeneration requested for section '{normalized_target_section}'.",
    )

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message="No temporary AI draft found for this store.",
        )
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = _get_or_rebuild_draft_metadata(
        store=store,
        draft_payload=current_draft,
        draft_meta=get_ai_draft_meta(store.id),
        rebuild_partial=True,
    )
    original_description = draft_meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message="Original user store description missing from metadata.",
        )
        raise ValidationError("Original user store description is missing from draft metadata")
    normalized_description = original_description.strip()

    clarification_history = (
        draft_meta.get("clarification_history")
        if isinstance(draft_meta.get("clarification_history"), list)
        else []
    )
    latest_clarification_input = draft_meta.get("latest_clarification_input")
    clarification_context = {
        "clarification_history": clarification_history,
        "latest_clarification_input": latest_clarification_input,
    }

    raw_round_count = draft_meta.get("clarification_round_count", 0)
    try:
        clarification_round_count = int(raw_round_count)
    except (TypeError, ValueError):
        clarification_round_count = 0

    repair_attempt_count = _safe_non_negative_int(
        draft_meta.get("repair_attempt_count"),
        0,
    )

    current_status = draft_meta.get("status")
    if current_status not in READY_FOR_REVIEW_WORKFLOW_STATUSES:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message="Partial regeneration requires ready_for_review workflow state.",
        )
        raise ValidationError(
            "Partial regeneration is allowed only when current workflow state is ready_for_review"
        )
    preserved_status = WORKFLOW_STATUS_READY_FOR_REVIEW
    preserved_mode = "draft_ready"
    preserved_step = "setting_up_store_configuration"

    available_theme_templates: list[str] | None = None
    if normalized_target_section == "theme":
        available_theme_templates = get_available_theme_template_names()
        if not available_theme_templates:
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="partial_regenerate",
                status="failed",
                message="No available theme templates found.",
            )
            raise ValidationError("No available theme templates found")

    try:
        provider = get_ai_provider_client()
        updated_draft: dict[str, Any] | None = None
        validation_feedback: str | None = None
        max_generation_attempts = 3

        for attempt_number in range(1, max_generation_attempts + 1):
            try:
                replacement_payload = _parse_provider_response_with_single_retry(
                    provider_call=lambda: provider.regenerate_store_draft_section(
                        tenant_id=normalized_tenant_id,
                        store_id=store.id,
                        target_section=normalized_target_section,
                        original_store_description=normalized_description,
                        current_draft=current_draft,
                        clarification_context=clarification_context,
                        available_theme_templates=available_theme_templates,
                        user_instruction=normalized_user_instruction,
                        validation_feedback=validation_feedback,
                        attempt_number=attempt_number,
                    ),
                    action="partial_regenerate",
                    store_id=store.id,
                )
                replacement_value = _extract_partial_section_replacement(
                    replacement_payload,
                    normalized_target_section,
                )

                candidate_draft = dict(current_draft)

                if normalized_target_section == "theme":
                    validated_theme = validate_theme_section(replacement_value)
                    _ensure_theme_template_is_available(
                        validated_theme,
                        available_theme_templates or [],
                    )
                    if validated_theme == current_draft.get("theme"):
                        raise AIDraftSchemaValidationError(
                            "Regenerated theme must be materially different from the current theme."
                        )
                    candidate_draft["theme"] = validated_theme
                elif normalized_target_section == "categories":
                    validated_categories = validate_categories_section(
                        replacement_value.get("categories")
                    )
                    category_names = [item["name"] for item in validated_categories]
                    validated_products = validate_products_section(
                        replacement_value.get("products"),
                        category_names,
                    )
                    if (
                        validated_categories == current_draft.get("categories")
                        and validated_products == current_draft.get("products")
                    ):
                        raise AIDraftSchemaValidationError(
                            "Regenerated categories and products must be materially different from the current draft."
                        )
                    candidate_draft["categories"] = validated_categories
                    candidate_draft["products"] = validated_products
                else:
                    existing_categories = validate_categories_section(current_draft.get("categories"))
                    category_names = [item["name"] for item in existing_categories]
                    validated_products = validate_products_section(
                        replacement_value,
                        category_names,
                    )
                    if validated_products == current_draft.get("products"):
                        raise AIDraftSchemaValidationError(
                            "Regenerated products must be materially different from the current products."
                        )
                    candidate_draft["products"] = validated_products

                updated_draft = candidate_draft
                break
            except (AIProviderParsingError, AIDraftSchemaValidationError) as attempt_exc:
                validation_feedback = str(attempt_exc)
                logger.warning(
                    "Partial regeneration attempt rejected; requesting corrected output. "
                    "store_id=%s, section=%s, attempt=%s/%s, reason=%s",
                    store.id,
                    normalized_target_section,
                    attempt_number,
                    max_generation_attempts,
                    validation_feedback,
                )
                if attempt_number == max_generation_attempts:
                    raise

        if updated_draft is None:
            raise AIDraftSchemaValidationError(
                "Partial regeneration did not produce a valid replacement."
            )

        save_ai_draft(store.id, updated_draft)
        save_ai_draft_meta(
            store.id,
            _with_workflow_counter_metadata(
                {
                    "status": preserved_status,
                    "current_step": preserved_step,
                    "mode": preserved_mode,
                    "is_fallback": False,
                    "original_user_store_description": normalized_description,
                    "latest_clarification_input": latest_clarification_input,
                    "clarification_history": clarification_history,
                    "last_partial_regeneration_target_section": normalized_target_section,
                    "last_operation": LAST_OPERATION_PARTIAL_REGENERATION,
                    "last_operation_status": LAST_OPERATION_STATUS_COMPLETED,
                },
                source_metadata=draft_meta,
                clarification_round_count=clarification_round_count,
                repair_attempt_count=repair_attempt_count,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="completed",
            message=f"Partial regeneration completed for section '{normalized_target_section}'.",
        )
        return updated_draft

    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Partial draft regeneration failed. Keeping current draft unchanged. "
            "store_id=%s, section=%s, error_type=%s, reason=%s",
            store.id,
            normalized_target_section,
            type(exc).__name__,
            str(exc),
            exc_info=True,
        )
        save_ai_draft_meta(
            store.id,
            _with_workflow_counter_metadata(
                {
                    "status": preserved_status,
                    "current_step": preserved_step,
                    "mode": preserved_mode,
                    "is_fallback": False,
                    "original_user_store_description": normalized_description,
                    "latest_clarification_input": latest_clarification_input,
                    "clarification_history": clarification_history,
                    "last_partial_regeneration_target_section": normalized_target_section,
                    "last_operation": LAST_OPERATION_PARTIAL_REGENERATION,
                    "last_operation_status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                    "last_operation_error_code": PARTIAL_REGENERATION_FAILED_ERROR_CODE,
                    "last_operation_user_message": PARTIAL_REGENERATION_FAILED_USER_MESSAGE,
                    "retry_allowed": True,
                },
                source_metadata=draft_meta,
                clarification_round_count=clarification_round_count,
                repair_attempt_count=repair_attempt_count,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message=str(exc),
        )
        raise ValidationError(PARTIAL_REGENERATION_FAILED_USER_MESSAGE) from exc
