"""
Compatibility facade for AI Store Creation services.

The implementation is split into focused modules. Public imports from this
module remain supported during the transition.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.core.exceptions import ValidationError

from stores.models import Store

from .agentic.feature_flags import is_agentic_workflow_enabled
from . import agentic_production_services as _agentic_production_services
from .constants import (
    AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE,
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
)
from .providers import get_ai_provider_client
from . import apply_services as _apply_services
from . import metadata_services as _metadata_services
from . import workflow_services as _workflow_services


@contextmanager
def _temporary_workflow_dependencies() -> Iterator[None]:
    """
    Bridge legacy services.py patch points only for the delegated workflow call.

    This exists for backward compatibility with callers and tests that patch
    services.py instead of the focused implementation modules.
    """
    original_provider = _workflow_services.get_ai_provider_client
    original_workflow_clarification_limit = _workflow_services.MAX_CLARIFICATION_ROUNDS
    original_workflow_repair_limit = _workflow_services.MAX_REPAIR_ATTEMPTS
    original_metadata_clarification_limit = _metadata_services.MAX_CLARIFICATION_ROUNDS
    original_metadata_repair_limit = _metadata_services.MAX_REPAIR_ATTEMPTS

    try:
        _workflow_services.get_ai_provider_client = get_ai_provider_client
        _workflow_services.MAX_CLARIFICATION_ROUNDS = MAX_CLARIFICATION_ROUNDS
        _workflow_services.MAX_REPAIR_ATTEMPTS = MAX_REPAIR_ATTEMPTS
        _metadata_services.MAX_CLARIFICATION_ROUNDS = MAX_CLARIFICATION_ROUNDS
        _metadata_services.MAX_REPAIR_ATTEMPTS = MAX_REPAIR_ATTEMPTS
        yield
    finally:
        _workflow_services.get_ai_provider_client = original_provider
        _workflow_services.MAX_CLARIFICATION_ROUNDS = (
            original_workflow_clarification_limit
        )
        _workflow_services.MAX_REPAIR_ATTEMPTS = original_workflow_repair_limit
        _metadata_services.MAX_CLARIFICATION_ROUNDS = (
            original_metadata_clarification_limit
        )
        _metadata_services.MAX_REPAIR_ATTEMPTS = original_metadata_repair_limit


def derive_store_name_from_description(user_description: str) -> str:
    return _workflow_services.derive_store_name_from_description(user_description)


def create_draft_store_for_ai_flow(
    user,
    tenant_id: int | None,
    *,
    name: str,
    description: str = "",
) -> Store:
    return _workflow_services.create_draft_store_for_ai_flow(
        user=user,
        tenant_id=tenant_id,
        name=name,
        description=description,
    )


def start_ai_draft_workflow(
    *,
    user,
    tenant_id: int | None,
    user_store_description: str,
) -> dict[str, Any]:
    if is_agentic_workflow_enabled():
        return _agentic_production_services.start_agentic_ai_draft_workflow(
            user=user,
            tenant_id=tenant_id,
            user_store_description=user_store_description,
        )

    with _temporary_workflow_dependencies():
        return _workflow_services.start_ai_draft_workflow(
            user=user,
            tenant_id=tenant_id,
            user_store_description=user_store_description,
        )


def generate_initial_store_draft(
    store_id: int,
    user,
    tenant_id: int | None,
    user_store_description: str,
) -> dict[str, Any]:
    _raise_if_agentic_session_exists(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    with _temporary_workflow_dependencies():
        return _workflow_services.generate_initial_store_draft(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
            user_store_description=user_store_description,
        )


def get_current_ai_draft(store_id: int, user, tenant_id: int | None) -> dict[str, Any]:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        return _agentic_production_services.get_current_agentic_ai_draft(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
        )

    return _workflow_services.get_current_ai_draft(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )


def process_clarification_round(
    store_id: int,
    user,
    tenant_id: int | None,
    clarification_answers: Any,
) -> dict[str, Any]:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        return _agentic_production_services.process_agentic_clarification_round(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
            clarification_answers=clarification_answers,
        )

    with _temporary_workflow_dependencies():
        return _workflow_services.process_clarification_round(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
            clarification_answers=clarification_answers,
        )


def regenerate_store_draft(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        with _temporary_workflow_dependencies():
            return _agentic_production_services.regenerate_current_agentic_ai_draft(
                store_id=store_id,
                user=user,
                tenant_id=tenant_id,
            )

    with _temporary_workflow_dependencies():
        return _workflow_services.regenerate_store_draft(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
        )


def regenerate_store_draft_section(
    store_id: int,
    user,
    tenant_id: int | None,
    target_section: str,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        with _temporary_workflow_dependencies():
            return _agentic_production_services.regenerate_current_agentic_ai_draft_section(
                store_id=store_id,
                user=user,
                tenant_id=tenant_id,
                target_section=target_section,
                user_instruction=user_instruction,
            )

    with _temporary_workflow_dependencies():
        return _workflow_services.regenerate_store_draft_section(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
            target_section=target_section,
            user_instruction=user_instruction,
        )


def apply_current_ai_draft_store_core(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    _raise_if_agentic_session_exists(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    return _apply_services.apply_current_ai_draft_store_core(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )


def apply_current_ai_draft_categories(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    _raise_if_agentic_session_exists(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    return _apply_services.apply_current_ai_draft_categories(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )


def apply_current_ai_draft_products(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    _raise_if_agentic_session_exists(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )
    return _apply_services.apply_current_ai_draft_products(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )


def apply_current_ai_draft_to_store(
    store_id: int,
    user,
    tenant_id: int | None,
) -> dict[str, Any]:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        return _agentic_production_services.apply_current_agentic_ai_draft_to_store(
            store_id=store_id,
            user=user,
            tenant_id=tenant_id,
        )

    return _apply_services.apply_current_ai_draft_to_store(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    )


def _raise_if_agentic_session_exists(
    *,
    store_id: int,
    user,
    tenant_id: int | None,
) -> None:
    if _agentic_production_services.has_existing_agentic_session(
        store_id=store_id,
        user=user,
        tenant_id=tenant_id,
    ):
        raise ValidationError(AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE)


__all__ = [
    "MAX_CLARIFICATION_ROUNDS",
    "MAX_REPAIR_ATTEMPTS",
    "get_ai_provider_client",
    "derive_store_name_from_description",
    "create_draft_store_for_ai_flow",
    "start_ai_draft_workflow",
    "generate_initial_store_draft",
    "get_current_ai_draft",
    "process_clarification_round",
    "regenerate_store_draft",
    "regenerate_store_draft_section",
    "apply_current_ai_draft_store_core",
    "apply_current_ai_draft_categories",
    "apply_current_ai_draft_products",
    "apply_current_ai_draft_to_store",
]