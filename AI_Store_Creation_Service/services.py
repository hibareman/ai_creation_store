"""
Service-layer helpers for AI Store Creation workflow.

This module is intentionally limited to focused workflow services.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.core.exceptions import ValidationError

from stores.models import Store

from .draft_store import get_ai_draft, get_ai_draft_meta, save_ai_draft, save_ai_draft_meta
from .parsers import AIProviderParsingError, parse_provider_raw_response_to_dict
from .providers import get_ai_provider_client
from .selectors import get_available_theme_template_names, get_store_for_ai_flow
from .validators import (
    AIDraftSchemaValidationError,
    build_ai_fallback_payload,
    detect_ai_response_mode,
    validate_basic_draft_schema,
    validate_categories_section,
    validate_products_section,
    validate_theme_section,
)


logger = logging.getLogger(__name__)


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
    7) on parsing/validation failure, save standardized fallback payload
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

    available_theme_templates = get_available_theme_template_names()
    if not available_theme_templates:
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
            store_id=store.id,
            user_store_description=normalized_description,
            available_theme_templates=available_theme_templates,
        )

        payload = parse_provider_raw_response_to_dict(raw_response)
        validate_basic_draft_schema(payload)
        mode = detect_ai_response_mode(payload)

        if mode == "draft_ready":
            validate_theme_section(payload["theme"])
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
        return payload
    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Initial AI draft generation failed; saving standardized fallback. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "failed",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": True,
                "reason": str(exc),
                "original_user_store_description": normalized_description,
            },
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

    current_draft = get_ai_draft(store.id)
    if current_draft is None:
        raise ValidationError("No temporary AI draft found for this store")

    draft_meta = get_ai_draft_meta(store.id) or {}
    current_status = draft_meta.get("status")
    if current_status != "needs_clarification":
        raise ValidationError("Current workflow state does not require clarification")

    if not current_draft.get("clarification_needed", False):
        raise ValidationError("Current draft is not in clarification mode")

    original_description = draft_meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
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
        return fallback_payload

    if clarification_answers is None:
        raise ValidationError("clarification_answers is required")

    if isinstance(clarification_answers, str):
        clarification_input = clarification_answers.strip()
    else:
        if clarification_answers in ({}, [], ()):
            raise ValidationError("clarification_answers is required")
        clarification_input = json.dumps(clarification_answers, ensure_ascii=False)

    if not clarification_input or clarification_input in {"null", "{}", "[]", '""'}:
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
            validate_theme_section(payload["theme"])
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
        return payload

    except (AIProviderParsingError, AIDraftSchemaValidationError, Exception) as exc:
        logger.warning(
            "Clarification round failed; saving standardized fallback. "
            "store_id=%s, reason=%s",
            store.id,
            str(exc),
        )
        fallback_payload = build_ai_fallback_payload()
        save_ai_draft(store.id, fallback_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "failed",
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": True,
                "reason": str(exc),
                "clarification_round_count": clarification_round_count,
                "original_user_store_description": original_description,
                "latest_clarification_input": clarification_input,
                "clarification_history": updated_history,
            },
        )
        return fallback_payload
