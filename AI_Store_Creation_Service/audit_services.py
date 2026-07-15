"""
Lightweight audit helpers for AI Store Creation workflows.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import AIStoreAuditLog


logger = logging.getLogger(__name__)


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


__all__ = ["_write_ai_audit_log"]
