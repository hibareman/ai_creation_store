"""
Service-layer helpers for AI Store Creation workflow.

This module is intentionally limited to focused workflow services.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db import transaction
from django.core.exceptions import ValidationError

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store
from themes.models import StoreThemeConfig

from .models import AIStoreAuditLog
from .draft_store import (
    delete_ai_draft,
    delete_ai_draft_meta,
    get_ai_draft,
    get_ai_draft_meta,
    save_ai_draft,
    save_ai_draft_meta,
)
from .parsers import AIProviderParsingError, parse_provider_raw_response_to_dict
from .providers import get_ai_provider_client
from .selectors import (
    get_available_theme_template_names,
    get_store_for_ai_flow,
    get_store_categories_for_ai_flow,
    get_store_products_for_ai_flow,
    get_store_theme_config_for_ai_flow,
    get_theme_template_by_exact_name,
)
from .validators import (
    AIDraftSchemaValidationError,
    build_ai_fallback_payload,
    detect_ai_response_mode,
    validate_basic_draft_schema,
    validate_categories_section,
    validate_products_section,
    validate_store_section,
    validate_store_settings_section,
    validate_theme_section,
)


logger = logging.getLogger(__name__)
_ALLOWED_PARTIAL_TARGET_SECTIONS = {"theme", "categories", "products"}


def _safe_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_ai_audit_log(
    *,
    tenant_id: Any,
    store_id: Any,
    actor_id: Any,
    action: str,
    status: str,
    message: str = "",
) -> None:
    """
    Write a lightweight AI audit row.

    Logging is intentionally non-critical and must never break the main flow.
    """
    try:
        AIStoreAuditLog.objects.create(
            tenant_id=_safe_int_or_none(tenant_id),
            store_id=_safe_int_or_none(store_id),
            actor_id=_safe_int_or_none(actor_id),
            action=action,
            status=status,
            message=(message or "")[:500],
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Non-critical AI audit logging failure. action=%s, status=%s, reason=%s",
            action,
            status,
            str(exc),
        )


def _ensure_theme_template_is_available(
    theme_data: dict[str, Any],
    available_theme_templates: list[str],
) -> None:
    """
    Ensure theme_template matches an exact currently available ThemeTemplate name.
    """
    selected_template_name = theme_data.get("theme_template")
    if selected_template_name not in set(available_theme_templates):
        raise AIDraftSchemaValidationError(
            "Theme field 'theme_template' must match an available ThemeTemplate name."
        )


def _build_recoverable_fallback_metadata(
    *,
    reason: str,
    original_user_store_description: str,
    clarification_round_count: int | None = None,
    latest_clarification_input: str | None = None,
    clarification_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "status": "needs_clarification",
        "current_step": "analyzing_description",
        "mode": "clarification",
        "is_fallback": True,
        "reason": reason,
        "original_user_store_description": original_user_store_description,
    }
    if clarification_round_count is not None:
        metadata["clarification_round_count"] = clarification_round_count
    if latest_clarification_input is not None:
        metadata["latest_clarification_input"] = latest_clarification_input
    if clarification_history is not None:
        metadata["clarification_history"] = clarification_history
    return metadata


def _extract_partial_section_replacement(
    payload: dict[str, Any],
    target_section: str,
) -> Any:
    """
    Extract section replacement from partial regeneration payload.

    Expected strict shape:
    - {"theme": {...}}
    - {"categories": [...]}
    - {"products": [...]}
    """
    if target_section not in payload:
        raise AIDraftSchemaValidationError(
            f"Partial regeneration payload must include top-level key '{target_section}'."
        )

    if len(payload) != 1:
        raise AIDraftSchemaValidationError(
            "Partial regeneration payload must include only the requested section key."
        )

    return payload[target_section]


def _normalize_category_name_for_compare(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def _normalize_category_name_for_store(name: str) -> str:
    return " ".join(name.strip().split())


def _normalize_sku_for_compare(sku: str) -> str:
    return " ".join(sku.strip().split()).casefold()


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
    7) on parsing/validation failure, save standardized clarification-style fallback payload
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise ValidationError("Authentication required")

    if tenant_id is None:
        raise ValidationError("Trusted tenant context is required")

    if not isinstance(user_store_description, str) or not user_store_description.strip():
        raise ValidationError("user_store_description is required")

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
        _write_ai_audit_log(
            tenant_id=store.tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="start_draft",
            status="failed",
            message="No available theme templates found.",
        )
        raise ValidationError("No available theme templates found")

    normalized_description = user_store_description.strip()
    save_ai_draft_meta(
        store.id,
        {
            "status": "processing",
            "current_step": "analyzing_description",
            "original_user_store_description": normalized_description,
            "is_fallback": False,
        },
    )

    try:
        provider = get_ai_provider_client()
        raw_response = provider.generate_store_draft(
            tenant_id=store.tenant_id,
            store_id=store.id,
            user_store_description=normalized_description,
            available_theme_templates=available_theme_templates,
        )

        payload = parse_provider_raw_response_to_dict(raw_response)
        validate_basic_draft_schema(payload)
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
            {
                "status": "needs_clarification" if mode == "clarification" else "draft_ready",
                "current_step": (
                    "analyzing_description"
                    if mode == "clarification"
                    else "setting_up_store_configuration"
                ),
                "mode": mode,
                "is_fallback": False,
                "original_user_store_description": normalized_description,
            },
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
            "Initial AI draft generation failed; saving standardized clarification-style fallback. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=str(exc),
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

    This service is read-only and does not mutate draft or database state.
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

    draft_meta = get_ai_draft_meta(store.id) or {}

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
    Orchestrate one clarification round (max 3 rounds) for temporary AI draft workflow.
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

    draft_meta = get_ai_draft_meta(store.id) or {}
    current_status = draft_meta.get("status")
    if current_status != "needs_clarification":
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

    if clarification_round_count >= 3:
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "failed",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": True,
                "reason": "Clarification round limit reached",
                "clarification_round_count": clarification_round_count,
                "original_user_store_description": original_description,
                "clarification_history": (
                    draft_meta.get("clarification_history")
                    if isinstance(draft_meta.get("clarification_history"), list)
                    else []
                ),
            },
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

    existing_history = (
        draft_meta.get("clarification_history")
        if isinstance(draft_meta.get("clarification_history"), list)
        else []
    )
    updated_history = [
        *existing_history,
        {
            "round": clarification_round_count + 1,
            "clarification_input": clarification_input,
        },
    ]

    save_ai_draft_meta(
        store.id,
        {
            "status": "processing",
            "current_step": "analyzing_description",
            "mode": "clarification",
            "is_fallback": False,
            "clarification_round_count": clarification_round_count,
            "original_user_store_description": original_description,
            "latest_clarification_input": clarification_input,
            "clarification_history": updated_history,
        },
    )

    try:
        provider = get_ai_provider_client()
        raw_response = provider.clarify_store_draft(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            current_draft=current_draft,
            prompt=clarification_input,
            context={
                "original_store_description": original_description,
                "clarification_round_count": clarification_round_count,
                "latest_clarification_input": clarification_input,
                "clarification_history": updated_history,
            },
        )

        payload = parse_provider_raw_response_to_dict(raw_response)
        validate_basic_draft_schema(payload)
        mode = detect_ai_response_mode(payload)

        new_round_count = clarification_round_count + 1

        if mode == "draft_ready":
            available_theme_templates = get_available_theme_template_names()
            if not available_theme_templates:
                raise AIDraftSchemaValidationError("No available theme templates found")
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
                {
                    "status": "draft_ready",
                    "current_step": "setting_up_store_configuration",
                    "mode": "draft_ready",
                    "is_fallback": False,
                    "clarification_round_count": new_round_count,
                    "original_user_store_description": original_description,
                    "latest_clarification_input": clarification_input,
                    "clarification_history": updated_history,
                },
            )
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="clarification_round",
                status="completed",
                message="Clarification round completed with draft_ready mode.",
            )
            return payload

        if new_round_count >= 3:
            fallback_payload = build_ai_fallback_payload()
            save_ai_draft(store.id, fallback_payload)
            save_ai_draft_meta(
                store.id,
                {
                    "status": "failed",
                    "current_step": "analyzing_description",
                    "mode": "clarification",
                    "is_fallback": True,
                    "reason": "Clarification round limit reached",
                    "clarification_round_count": new_round_count,
                    "original_user_store_description": original_description,
                    "latest_clarification_input": clarification_input,
                    "clarification_history": updated_history,
                },
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

        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": new_round_count,
                "original_user_store_description": original_description,
                "latest_clarification_input": clarification_input,
                "clarification_history": updated_history,
            },
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
            "Clarification round failed; saving standardized clarification-style fallback. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=str(exc),
                original_user_store_description=original_description,
                clarification_round_count=clarification_round_count,
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
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Orchestrate full temporary draft regeneration for the same store/session.

    Approved constraints:
    - no new free-text regeneration prompt is accepted
    - same store_id, same authenticated owner, same trusted tenant context
    - reuse original description + current draft + saved clarification context/history
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
        action="full_regenerate",
        status="requested",
        message="Full regeneration requested.",
    )

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="full_regenerate",
            status="failed",
            message="No temporary AI draft found for this store.",
        )
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    original_description = draft_meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="full_regenerate",
            status="failed",
            message="Original user store description missing from metadata.",
        )
        raise ValidationError("Original user store description is missing from draft metadata")
    normalized_description = original_description.strip()

    available_theme_templates = get_available_theme_template_names()
    if not available_theme_templates:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="full_regenerate",
            status="failed",
            message="No available theme templates found.",
        )
        raise ValidationError("No available theme templates found")

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

    save_ai_draft_meta(
        store.id,
        {
            "status": "processing",
            "current_step": "analyzing_description",
            "is_fallback": False,
            "original_user_store_description": normalized_description,
            "clarification_round_count": clarification_round_count,
            "latest_clarification_input": latest_clarification_input,
            "clarification_history": clarification_history,
        },
    )

    try:
        provider = get_ai_provider_client()
        raw_response = provider.regenerate_store_draft(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            original_store_description=normalized_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )

        payload = parse_provider_raw_response_to_dict(raw_response)
        validate_basic_draft_schema(payload)
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
                {
                    "status": "draft_ready",
                    "current_step": "setting_up_store_configuration",
                    "mode": "draft_ready",
                    "is_fallback": False,
                    "original_user_store_description": normalized_description,
                    "clarification_round_count": clarification_round_count,
                    "latest_clarification_input": latest_clarification_input,
                    "clarification_history": clarification_history,
                },
            )
            _write_ai_audit_log(
                tenant_id=normalized_tenant_id,
                store_id=store.id,
                actor_id=getattr(user, "id", None),
                action="full_regenerate",
                status="completed",
                message="Full regeneration completed with draft_ready mode.",
            )
            return payload

        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "needs_clarification",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "original_user_store_description": normalized_description,
                "clarification_round_count": clarification_round_count,
                "latest_clarification_input": latest_clarification_input,
                "clarification_history": clarification_history,
            },
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="full_regenerate",
            status="completed",
            message="Full regeneration completed with clarification mode.",
        )
        return payload

    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Full draft regeneration failed; saving standardized clarification-style fallback. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            _build_recoverable_fallback_metadata(
                reason=str(exc),
                original_user_store_description=normalized_description,
                clarification_round_count=clarification_round_count,
                latest_clarification_input=latest_clarification_input,
                clarification_history=clarification_history,
            ),
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="full_regenerate",
            status="failed",
            message=str(exc),
        )
        return fallback_payload


def regenerate_store_draft_section(
    store_id: int,
    user,
    tenant_id: int | None,
    target_section: str,
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

    draft_meta = get_ai_draft_meta(store.id) or {}
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

    current_status = draft_meta.get("status")
    if current_status != "draft_ready":
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message="Partial regeneration requires draft_ready workflow state.",
        )
        raise ValidationError(
            "Partial regeneration is allowed only when current workflow state is draft_ready"
        )
    preserved_status = "draft_ready"
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
        raw_response = provider.regenerate_store_draft_section(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            target_section=normalized_target_section,
            original_store_description=normalized_description,
            current_draft=current_draft,
            clarification_context=clarification_context,
            available_theme_templates=available_theme_templates,
        )

        replacement_payload = parse_provider_raw_response_to_dict(raw_response)
        replacement_value = _extract_partial_section_replacement(
            replacement_payload,
            normalized_target_section,
        )

        updated_draft = dict(current_draft)

        if normalized_target_section == "theme":
            validated_theme = validate_theme_section(replacement_value)
            _ensure_theme_template_is_available(
                validated_theme,
                available_theme_templates or [],
            )
            updated_draft["theme"] = validated_theme
        elif normalized_target_section == "categories":
            validated_categories = validate_categories_section(replacement_value)
            # Keep current draft coherent: existing products must stay valid against new categories.
            category_names = [item["name"] for item in validated_categories]
            validate_products_section(current_draft.get("products"), category_names)
            updated_draft["categories"] = validated_categories
        else:
            existing_categories = validate_categories_section(current_draft.get("categories"))
            category_names = [item["name"] for item in existing_categories]
            updated_draft["products"] = validate_products_section(
                replacement_value,
                category_names,
            )

        save_ai_draft(store.id, updated_draft)
        save_ai_draft_meta(
            store.id,
            {
                "status": preserved_status,
                "current_step": preserved_step,
                "mode": preserved_mode,
                "is_fallback": False,
                "original_user_store_description": normalized_description,
                "clarification_round_count": clarification_round_count,
                "latest_clarification_input": latest_clarification_input,
                "clarification_history": clarification_history,
                "last_partial_regeneration_target_section": normalized_target_section,
            },
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
            "store_id=%s, section=%s, reason=%s",
            store.id,
            normalized_target_section,
            str(exc),
        )
        save_ai_draft_meta(
            store.id,
            {
                "status": preserved_status,
                "current_step": preserved_step,
                "mode": preserved_mode,
                "is_fallback": False,
                "original_user_store_description": normalized_description,
                "clarification_round_count": clarification_round_count,
                "latest_clarification_input": latest_clarification_input,
                "clarification_history": clarification_history,
                "last_partial_regeneration_target_section": normalized_target_section,
                "last_partial_regeneration_error": str(exc),
            },
        )
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="partial_regenerate",
            status="failed",
            message=str(exc),
        )
        raise ValidationError(
            f"Partial regeneration failed for section '{normalized_target_section}'."
        ) from exc


def apply_current_ai_draft_store_core(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply current temporary AI draft to Store + StoreThemeConfig only.

    Scope is intentionally limited:
    - update existing Store from draft.store
    - create/update StoreThemeConfig from draft.theme
    - do not apply categories/products in this step
    - do not delete draft cache or perform final status transition
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

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    if draft_meta.get("status") != "draft_ready":
        raise ValidationError("Current workflow state is not draft_ready")

    try:
        validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        store_section = validate_store_section(current_draft["store"])
        validate_store_settings_section(current_draft["store_settings"])
        store_name = store_section["name"]
        store_description = store_section["description"]

        theme_data = validate_theme_section(current_draft["theme"])
        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validate_products_section(current_draft["products"], category_names)

        available_theme_templates = get_available_theme_template_names()
        if not available_theme_templates:
            raise AIDraftSchemaValidationError("No available theme templates found")
        _ensure_theme_template_is_available(theme_data, available_theme_templates)

        theme_template_name = str(theme_data["theme_template"]).strip()
        theme_template_obj = get_theme_template_by_exact_name(theme_template_name)
        if theme_template_obj is None:
            raise AIDraftSchemaValidationError(
                "Theme field 'theme_template' does not resolve to an existing ThemeTemplate."
            )
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    with transaction.atomic():
        store.name = store_name.strip()
        store.description = store_description
        store.save()

        store_theme_config = get_store_theme_config_for_ai_flow(
            store_id=store.id,
            user=user,
            tenant_id=normalized_tenant_id,
        )
        if store_theme_config is None:
            store_theme_config = StoreThemeConfig.objects.create(
                store=store,
                theme_template=theme_template_obj,
                primary_color=theme_data["primary_color"],
                secondary_color=theme_data["secondary_color"],
                font_family=theme_data["font_family"],
                logo_url=theme_data["logo_url"],
                banner_url=theme_data["banner_url"],
            )
        else:
            store_theme_config.theme_template = theme_template_obj
            store_theme_config.primary_color = theme_data["primary_color"]
            store_theme_config.secondary_color = theme_data["secondary_color"]
            store_theme_config.font_family = theme_data["font_family"]
            store_theme_config.logo_url = theme_data["logo_url"]
            store_theme_config.banner_url = theme_data["banner_url"]
            store_theme_config.save()

    return {
        "store_id": store.id,
        "draft_status": "draft_ready",
        "store": {
            "name": store.name,
            "description": store.description,
        },
        "theme": {
            "theme_template": store_theme_config.theme_template.name,
            "primary_color": store_theme_config.primary_color,
            "secondary_color": store_theme_config.secondary_color,
            "font_family": store_theme_config.font_family,
            "logo_url": store_theme_config.logo_url,
            "banner_url": store_theme_config.banner_url,
        },
    }


def apply_current_ai_draft_categories(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply only the categories section of the current temporary AI draft.

    Scope is intentionally limited:
    - apply Category only (safe additive: create missing, skip existing)
    - no Store creation/update
    - no StoreThemeConfig/Product/Inventory apply
    - no draft deletion
    - no final status transition
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

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    if draft_meta.get("status") != "draft_ready":
        raise ValidationError("Current workflow state is not draft_ready")

    try:
        validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validate_products_section(current_draft["products"], category_names)
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    existing_categories_qs = get_store_categories_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    existing_names_normalized = {
        _normalize_category_name_for_compare(category.name)
        for category in existing_categories_qs
    }

    created_categories: list[str] = []
    skipped_categories: list[str] = []

    try:
        with transaction.atomic():
            for item in validated_categories:
                draft_name = str(item["name"])
                normalized_name = _normalize_category_name_for_compare(draft_name)

                if normalized_name in existing_names_normalized:
                    skipped_categories.append(_normalize_category_name_for_store(draft_name))
                    continue

                safe_name = _normalize_category_name_for_store(draft_name)
                Category.objects.create(
                    store=store,
                    tenant_id=normalized_tenant_id,
                    name=safe_name,
                )
                existing_names_normalized.add(normalized_name)
                created_categories.append(safe_name)
    except Exception as exc:
        raise ValidationError(f"Failed to apply categories from current draft: {exc}") from exc

    return {
        "store_id": store.id,
        "draft_status": "draft_ready",
        "created_categories": created_categories,
        "skipped_categories": skipped_categories,
    }


def apply_current_ai_draft_products(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Apply only the products section of the current temporary AI draft.

    Scope is intentionally limited:
    - apply Product only (safe additive: create missing by SKU, skip existing)
    - no Store creation/update
    - no StoreThemeConfig/Category/Inventory apply
    - no draft deletion
    - no final status transition
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

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    if draft_meta.get("status") != "draft_ready":
        raise ValidationError("Current workflow state is not draft_ready")

    try:
        validate_basic_draft_schema(current_draft)
        mode = detect_ai_response_mode(current_draft)
        if mode != "draft_ready":
            raise AIDraftSchemaValidationError("Current draft payload is not draft_ready")

        validated_categories = validate_categories_section(current_draft["categories"])
        category_names = [item["name"] for item in validated_categories]
        validated_products = validate_products_section(current_draft["products"], category_names)
    except AIDraftSchemaValidationError as exc:
        raise ValidationError(str(exc)) from exc

    existing_categories_qs = get_store_categories_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    category_by_normalized_name = {
        _normalize_category_name_for_compare(category.name): category
        for category in existing_categories_qs
    }

    for item in validated_products:
        normalized_category_name = _normalize_category_name_for_compare(
            str(item["category_name"])
        )
        if normalized_category_name not in category_by_normalized_name:
            raise ValidationError(
                "Failed to resolve product category_name to an existing category in this store"
            )

    existing_products_qs = get_store_products_for_ai_flow(
        store_id=store.id,
        user=user,
        tenant_id=normalized_tenant_id,
    )
    existing_skus_normalized = {
        _normalize_sku_for_compare(product.sku)
        for product in existing_products_qs
    }

    created_products: list[str] = []
    skipped_products: list[str] = []

    try:
        with transaction.atomic():
            for item in validated_products:
                draft_sku = str(item["sku"])
                normalized_sku = _normalize_sku_for_compare(draft_sku)

                if normalized_sku in existing_skus_normalized:
                    skipped_products.append(" ".join(draft_sku.strip().split()))
                    continue

                normalized_category_name = _normalize_category_name_for_compare(
                    str(item["category_name"])
                )
                resolved_category = category_by_normalized_name[normalized_category_name]

                safe_sku = " ".join(draft_sku.strip().split())
                created_product = Product.objects.create(
                    store=store,
                    tenant_id=normalized_tenant_id,
                    category=resolved_category,
                    name=str(item["name"]).strip(),
                    description=str(item["description"]),
                    price=item["price"],
                    sku=safe_sku,
                )

                Inventory.objects.create(
                    product=created_product,
                    stock_quantity=item["stock_quantity"],
                )

                image_url = str(item["image_url"]).strip()
                if image_url:
                    ProductImage.objects.create(
                        product=created_product,
                        image_url=image_url,
                    )
                existing_skus_normalized.add(normalized_sku)
                created_products.append(safe_sku)
    except Exception as exc:
        raise ValidationError(f"Failed to apply products from current draft: {exc}") from exc

    return {
        "store_id": store.id,
        "draft_status": "draft_ready",
        "created_products": created_products,
        "skipped_products": skipped_products,
    }


def apply_current_ai_draft_to_store(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    """
    Confirm/apply the current AI draft completely using existing sub-services.

    Apply order (strict):
    1) store core
    2) categories
    3) products
    4) transition store status from draft -> setup

    Cache cleanup rule:
    - delete draft + metadata only after successful DB commit via on_commit.
    - response indicates cleanup was scheduled, not synchronously completed inline.
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
        action="apply_draft",
        status="requested",
        message="Apply current AI draft requested.",
    )

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message="No temporary AI draft found for this store.",
        )
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    if draft_meta.get("status") != "draft_ready":
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message="Current workflow state is not draft_ready.",
        )
        raise ValidationError("Current workflow state is not draft_ready")

    def _cleanup_draft_after_commit() -> None:
        try:
            delete_ai_draft(store.id)
            delete_ai_draft_meta(store.id)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Draft cleanup after apply commit failed. store_id=%s, reason=%s",
                store.id,
                str(exc),
            )

    try:
        with transaction.atomic():
            apply_current_ai_draft_store_core(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            categories_result = apply_current_ai_draft_categories(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )
            products_result = apply_current_ai_draft_products(
                store_id=store.id,
                user=user,
                tenant_id=normalized_tenant_id,
            )

            store.status = "setup"
            store.save(update_fields=["status", "updated_at"])

            transaction.on_commit(_cleanup_draft_after_commit)
    except Exception as exc:
        _write_ai_audit_log(
            tenant_id=normalized_tenant_id,
            store_id=store.id,
            actor_id=getattr(user, "id", None),
            action="apply_draft",
            status="failed",
            message=str(exc),
        )
        raise

    _write_ai_audit_log(
        tenant_id=normalized_tenant_id,
        store_id=store.id,
        actor_id=getattr(user, "id", None),
        action="apply_draft",
        status="completed",
        message="Current AI draft applied successfully.",
    )
    return {
        "store_id": store.id,
        "final_status": "setup",
        "store_core_applied": True,
        "categories": {
            "created": categories_result.get("created_categories", []),
            "skipped": categories_result.get("skipped_categories", []),
        },
        "products": {
            "created": products_result.get("created_products", []),
            "skipped": products_result.get("skipped_products", []),
        },
        "draft_cleanup_scheduled": True,
    }
