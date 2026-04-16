"""
AI Store Creation key naming strategy (foundation only).

This module defines Redis/cache key shapes for temporary AI draft storage.
No storage operations are implemented here.
"""

from django.conf import settings


# Key segments
AI_DRAFT_SCOPE = "store"
AI_DRAFT_MAIN_SUFFIX = "draft"
AI_DRAFT_META_SUFFIX = "meta"


def _normalize_store_id(store_id: int) -> int:
    """
    Validate and normalize store_id for key building.
    """
    normalized = int(store_id)
    if normalized <= 0:
        raise ValueError("store_id must be a positive integer")
    return normalized


def build_ai_draft_key(store_id: int) -> str:
    """
    Main key for the full generated AI draft JSON.

    Pattern:
    <AI_DRAFT_PREFIX>:store:<store_id>:draft
    """
    sid = _normalize_store_id(store_id)
    return f"{settings.AI_DRAFT_PREFIX}:{AI_DRAFT_SCOPE}:{sid}:{AI_DRAFT_MAIN_SUFFIX}"


def build_ai_draft_meta_key(store_id: int) -> str:
    """
    Optional metadata key for lightweight workflow state (e.g. status, step).

    Pattern:
    <AI_DRAFT_PREFIX>:store:<store_id>:meta
    """
    sid = _normalize_store_id(store_id)
    return f"{settings.AI_DRAFT_PREFIX}:{AI_DRAFT_SCOPE}:{sid}:{AI_DRAFT_META_SUFFIX}"
