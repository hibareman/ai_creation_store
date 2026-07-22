"""
Temporary draft storage adapter for AI Store Creation.

This module is intentionally limited to cache/Redis storage helpers only.
No business rules, ownership checks, workflow logic, or provider calls.
"""

import json
from typing import Any

from django.conf import settings
from django.core.cache import cache

from .constants import build_ai_draft_key, build_ai_draft_meta_key


def _serialize_json(payload: dict[str, Any]) -> str:
    """Serialize payload to a compact JSON string."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _deserialize_json(raw_value: Any) -> dict[str, Any] | None:
    """Deserialize cached JSON value into a dict."""
    if raw_value is None:
        return None

    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8")

    if not isinstance(raw_value, str):
        return None

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return None

    return parsed if isinstance(parsed, dict) else None


def save_ai_draft(store_id: int, draft_json: dict[str, Any], ttl_seconds: int | None = None) -> None:
    """
    Save the full generated draft JSON for a store with TTL.
    """
    key = build_ai_draft_key(store_id)
    timeout = settings.AI_DRAFT_TTL if ttl_seconds is None else int(ttl_seconds)
    serialized = _serialize_json(draft_json)
    cache.set(key, serialized, timeout=timeout)


def get_ai_draft(store_id: int) -> dict[str, Any] | None:
    """
    Retrieve the full generated draft JSON for a store.
    """
    key = build_ai_draft_key(store_id)
    raw_value = cache.get(key)
    return _deserialize_json(raw_value)


def delete_ai_draft(store_id: int) -> bool:
    """
    Delete the full generated draft JSON for a store.
    """
    key = build_ai_draft_key(store_id)
    return cache.delete(key)


def save_ai_draft_meta(
    store_id: int,
    metadata: dict[str, Any],
    ttl_seconds: int | None = None,
) -> None:
    """
    Save lightweight metadata (e.g. status/current step) for a store draft.
    """
    key = build_ai_draft_meta_key(store_id)
    timeout = settings.AI_DRAFT_TTL if ttl_seconds is None else int(ttl_seconds)
    serialized = _serialize_json(metadata)
    cache.set(key, serialized, timeout=timeout)


def get_ai_draft_meta(store_id: int) -> dict[str, Any] | None:
    """
    Retrieve lightweight metadata for a store draft.
    """
    key = build_ai_draft_meta_key(store_id)
    raw_value = cache.get(key)
    return _deserialize_json(raw_value)


def delete_ai_draft_meta(store_id: int) -> bool:
    """
    Delete lightweight metadata for a store draft.
    """
    key = build_ai_draft_meta_key(store_id)
    return cache.delete(key)
