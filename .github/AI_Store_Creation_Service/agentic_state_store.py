"""Cache-backed persistence for agentic AI Store Creation sessions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django.conf import settings
from django.core.cache import cache

from .constants import (
    AI_AGENTIC_STATE_MAX_BYTES,
    AI_AGENTIC_STATE_SCHEMA_VERSION,
    build_ai_agentic_state_key,
)


_ENVELOPE_KEYS = {"schema_version", "tenant_id", "store_id", "user_id", "state"}
_DEFAULT_TTL_SECONDS = 3600


class AgenticStateStoreError(ValueError):
    """Raised when an agentic session cannot be safely persisted."""


def save_agentic_workflow_state(
    *,
    tenant_id: Any,
    store_id: Any,
    user_id: Any,
    state: Any,
    ttl_seconds: Any = None,
) -> None:
    normalized_tenant_id = _validate_positive_int(tenant_id, field_name="tenant_id")
    normalized_store_id = _validate_positive_int(store_id, field_name="store_id")
    normalized_user_id = _validate_positive_int(user_id, field_name="user_id")
    normalized_state = _normalize_state(
        state=state,
        tenant_id=normalized_tenant_id,
        store_id=normalized_store_id,
        user_id=normalized_user_id,
    )
    envelope = {
        "schema_version": AI_AGENTIC_STATE_SCHEMA_VERSION,
        "tenant_id": normalized_tenant_id,
        "store_id": normalized_store_id,
        "user_id": normalized_user_id,
        "state": normalized_state,
    }
    serialized = _serialize_envelope(envelope)
    if len(serialized.encode("utf-8")) > AI_AGENTIC_STATE_MAX_BYTES:
        raise AgenticStateStoreError("Agentic session is too large to cache.")

    key = build_ai_agentic_state_key(
        tenant_id=normalized_tenant_id,
        store_id=normalized_store_id,
    )
    timeout = _resolve_ttl(ttl_seconds)
    try:
        cache.set(key, serialized, timeout=timeout)
    except Exception as exc:
        raise AgenticStateStoreError("Agentic session could not be saved.") from exc


def get_agentic_workflow_state(
    *,
    tenant_id: Any,
    store_id: Any,
    user_id: Any,
) -> dict[str, Any] | None:
    try:
        normalized_tenant_id = _validate_positive_int(tenant_id, field_name="tenant_id")
        normalized_store_id = _validate_positive_int(store_id, field_name="store_id")
        normalized_user_id = _validate_positive_int(user_id, field_name="user_id")
        key = build_ai_agentic_state_key(
            tenant_id=normalized_tenant_id,
            store_id=normalized_store_id,
        )
        raw_value = cache.get(key)
    except Exception:
        return None

    envelope = _deserialize_envelope(raw_value)
    if envelope is None:
        return None
    state = _state_from_envelope(
        envelope,
        tenant_id=normalized_tenant_id,
        store_id=normalized_store_id,
        user_id=normalized_user_id,
    )
    return _json_defensive_copy(state) if state is not None else None


def delete_agentic_workflow_state(
    *,
    tenant_id: Any,
    store_id: Any,
    user_id: Any,
) -> bool:
    try:
        normalized_tenant_id = _validate_positive_int(tenant_id, field_name="tenant_id")
        normalized_store_id = _validate_positive_int(store_id, field_name="store_id")
        normalized_user_id = _validate_positive_int(user_id, field_name="user_id")
        key = build_ai_agentic_state_key(
            tenant_id=normalized_tenant_id,
            store_id=normalized_store_id,
        )
        envelope = _deserialize_envelope(cache.get(key))
        if (
            envelope is None
            or _state_from_envelope(
                envelope,
                tenant_id=normalized_tenant_id,
                store_id=normalized_store_id,
                user_id=normalized_user_id,
            )
            is None
        ):
            return False
        return bool(cache.delete(key))
    except Exception:
        return False


def _validate_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AgenticStateStoreError(f"{field_name} must be a positive integer.")
    return value


def _normalize_state(
    *,
    state: Any,
    tenant_id: int,
    store_id: int,
    user_id: int,
) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise AgenticStateStoreError("Agentic state must be an object.")
    if not _identity_matches(state.get("tenant_id"), tenant_id):
        raise AgenticStateStoreError("Agentic state tenant identity mismatch.")
    if not _identity_matches(state.get("store_id"), store_id):
        raise AgenticStateStoreError("Agentic state store identity mismatch.")
    if not _identity_matches(state.get("user_id"), user_id):
        raise AgenticStateStoreError("Agentic state user identity mismatch.")
    try:
        return _json_defensive_copy(dict(deepcopy(state)))
    except Exception as exc:
        raise AgenticStateStoreError("Agentic state must be valid JSON.") from exc


def _identity_matches(value: Any, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _serialize_envelope(envelope: dict[str, Any]) -> str:
    if set(envelope) != _ENVELOPE_KEYS:
        raise AgenticStateStoreError("Agentic envelope contract mismatch.")
    try:
        return json.dumps(
            envelope,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AgenticStateStoreError("Agentic envelope must be valid JSON.") from exc


def _deserialize_envelope(raw_value: Any) -> dict[str, Any] | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bytes):
        try:
            raw_value = raw_value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw_value, str):
        return None
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, Mapping) or set(parsed) != _ENVELOPE_KEYS:
        return None
    return dict(parsed)


def _state_from_envelope(
    envelope: Mapping[str, Any],
    *,
    tenant_id: int,
    store_id: int,
    user_id: int,
) -> dict[str, Any] | None:
    if envelope.get("schema_version") != AI_AGENTIC_STATE_SCHEMA_VERSION:
        return None
    if not _identity_matches(envelope.get("tenant_id"), tenant_id):
        return None
    if not _identity_matches(envelope.get("store_id"), store_id):
        return None
    if not _identity_matches(envelope.get("user_id"), user_id):
        return None

    state = envelope.get("state")
    if not isinstance(state, Mapping):
        return None
    if not _identity_matches(state.get("tenant_id"), tenant_id):
        return None
    if not _identity_matches(state.get("store_id"), store_id):
        return None
    if not _identity_matches(state.get("user_id"), user_id):
        return None
    try:
        return _json_defensive_copy(dict(state))
    except (TypeError, ValueError):
        return None


def _resolve_ttl(ttl_seconds: Any = None) -> int:
    if ttl_seconds is not None:
        return _validate_ttl(ttl_seconds)

    for setting_name in (
        "AI_AGENTIC_STATE_CACHE_TTL",
        "AI_DRAFT_CACHE_TTL",
        "AI_DRAFT_TTL",
    ):
        if hasattr(settings, setting_name):
            value = getattr(settings, setting_name)
            try:
                return _validate_ttl(value)
            except AgenticStateStoreError:
                continue
    return _DEFAULT_TTL_SECONDS


def _validate_ttl(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AgenticStateStoreError("Agentic session TTL must be a positive integer.")
    return value


def _json_defensive_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


__all__ = [
    "AgenticStateStoreError",
    "delete_agentic_workflow_state",
    "get_agentic_workflow_state",
    "save_agentic_workflow_state",
]
