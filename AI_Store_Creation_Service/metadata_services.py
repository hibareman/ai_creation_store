"""
Django cache workflow metadata helpers for AI Store Creation.
"""

from __future__ import annotations

from typing import Any, Mapping

from stores.models import Store

from .constants import (
    AI_WORKFLOW_STATUSES,
    LEGACY_WORKFLOW_STATUS_DRAFT_READY,
    LEGACY_WORKFLOW_STATUS_FAILED,
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)
from .draft_store import save_ai_draft_meta
from .exceptions import AIDraftSchemaValidationError, AIProviderParsingError
from .validators import detect_ai_response_mode, validate_basic_draft_schema


def _safe_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized >= 0 else default


def _build_workflow_counter_metadata(
    source_metadata: Mapping[str, Any] | None = None,
    *,
    clarification_round_count: Any = None,
    repair_attempt_count: Any = None,
) -> dict[str, int]:
    source = source_metadata if isinstance(source_metadata, Mapping) else {}
    clarification_value = (
        clarification_round_count
        if clarification_round_count is not None
        else source.get("clarification_round_count", 0)
    )
    repair_value = (
        repair_attempt_count
        if repair_attempt_count is not None
        else source.get("repair_attempt_count", 0)
    )
    return {
        "clarification_round_count": _safe_non_negative_int(clarification_value),
        "repair_attempt_count": _safe_non_negative_int(repair_value),
        "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
        "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
    }


def _with_workflow_counter_metadata(
    metadata: Mapping[str, Any],
    *,
    source_metadata: Mapping[str, Any] | None = None,
    clarification_round_count: Any = None,
    repair_attempt_count: Any = None,
) -> dict[str, Any]:
    enriched = dict(metadata)
    enriched.update(
        _build_workflow_counter_metadata(
            source_metadata or metadata,
            clarification_round_count=clarification_round_count,
            repair_attempt_count=repair_attempt_count,
        )
    )
    return enriched


def _normalize_cached_workflow_status(status: Any) -> str | None:
    if status == LEGACY_WORKFLOW_STATUS_DRAFT_READY:
        return WORKFLOW_STATUS_READY_FOR_REVIEW
    if status == LEGACY_WORKFLOW_STATUS_FAILED:
        return WORKFLOW_STATUS_FAILED_RECOVERABLE
    if isinstance(status, str) and status in AI_WORKFLOW_STATUSES:
        return status
    return None


def _build_ready_for_review_metadata(
    metadata: Mapping[str, Any],
    *,
    source_metadata: Mapping[str, Any] | None = None,
    clarification_round_count: Any = None,
    repair_attempt_count: Any = None,
) -> dict[str, Any]:
    enriched = dict(metadata)
    enriched["status"] = WORKFLOW_STATUS_READY_FOR_REVIEW
    enriched["mode"] = "draft_ready"
    enriched["is_fallback"] = False
    return _with_workflow_counter_metadata(
        enriched,
        source_metadata=source_metadata,
        clarification_round_count=clarification_round_count,
        repair_attempt_count=repair_attempt_count,
    )


def _build_recoverable_failure_metadata(
    *,
    source_metadata: Mapping[str, Any] | None = None,
    error_code: str = RECOVERABLE_FAILURE_ERROR_CODE,
    user_message: str = RECOVERABLE_FAILURE_USER_MESSAGE,
    clarification_round_count: Any = None,
    repair_attempt_count: Any = None,
    latest_clarification_input: str | None = None,
    clarification_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
        "current_step": "recoverable_failure",
        "mode": "failed_recoverable",
        "is_fallback": True,
        "error_code": error_code,
        "user_message": user_message,
        "retry_allowed": True,
        "manual_edit_allowed": True,
    }
    metadata = _with_workflow_counter_metadata(
        metadata,
        source_metadata=source_metadata,
        clarification_round_count=clarification_round_count,
        repair_attempt_count=repair_attempt_count,
    )
    if latest_clarification_input is not None:
        metadata["latest_clarification_input"] = latest_clarification_input
    if clarification_history is not None:
        metadata["clarification_history"] = clarification_history
    return metadata


def _recoverable_error_code_for_exception(exc: Exception) -> str:
    if isinstance(exc, AIProviderParsingError):
        return "ai_output_parse_failed"
    if isinstance(exc, AIDraftSchemaValidationError):
        return "ai_validation_failed"
    return RECOVERABLE_FAILURE_ERROR_CODE


def is_legacy_clarification_fallback(
    draft_payload: Mapping[str, Any],
    draft_metadata: Mapping[str, Any],
) -> bool:
    """
    Detect old technical-failure drafts stored as fake clarification questions.
    """
    if not isinstance(draft_payload, Mapping) or not isinstance(draft_metadata, Mapping):
        return False

    if (
        draft_metadata.get("status") == WORKFLOW_STATUS_NEEDS_CLARIFICATION
        and draft_metadata.get("is_fallback") is True
    ):
        return True

    return (
        draft_metadata.get("is_fallback") is True
        and draft_payload.get("clarification_needed") is True
        and isinstance(draft_payload.get("clarification_questions"), list)
        and bool(draft_payload.get("clarification_questions"))
    )


def _infer_mode_from_draft_payload(draft_payload: Mapping[str, Any]) -> str | None:
    if (
        draft_payload.get("clarification_needed") is False
        and draft_payload.get("clarification_questions") == []
        and (
            draft_payload.get("error_code")
            or draft_payload.get("retry_allowed") is True
            or draft_payload.get("manual_edit_allowed") is True
        )
    ):
        return "failed_recoverable"

    try:
        normalized_draft = validate_basic_draft_schema(draft_payload)
        return detect_ai_response_mode(normalized_draft)
    except Exception:
        return None


def _derive_original_description_fallback(
    *,
    store: Store,
    draft_payload: Mapping[str, Any],
    draft_meta: Mapping[str, Any],
) -> str:
    candidates: list[Any] = [
        draft_meta.get("original_user_store_description"),
        getattr(store, "description", ""),
    ]

    store_section = draft_payload.get("store")
    if isinstance(store_section, Mapping):
        candidates.append(store_section.get("description"))
        candidates.append(store_section.get("name"))

    candidates.append(getattr(store, "name", ""))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return " ".join(candidate.strip().split())
    return ""


def _get_or_rebuild_draft_metadata(
    *,
    store: Store,
    draft_payload: Mapping[str, Any],
    draft_meta: Mapping[str, Any] | None,
    rebuild_partial: bool,
) -> dict[str, Any]:
    meta: dict[str, Any] = dict(draft_meta) if isinstance(draft_meta, Mapping) else {}
    original_meta = dict(meta)

    meta = _with_workflow_counter_metadata(meta)

    if is_legacy_clarification_fallback(draft_payload, original_meta):
        legacy_original_description = original_meta.get("original_user_store_description")
        meta = _build_recoverable_failure_metadata(
            source_metadata=meta,
            error_code=RECOVERABLE_FAILURE_ERROR_CODE,
            clarification_round_count=meta.get("clarification_round_count"),
            repair_attempt_count=meta.get("repair_attempt_count"),
            latest_clarification_input=(
                original_meta.get("latest_clarification_input")
                if isinstance(original_meta.get("latest_clarification_input"), str)
                else None
            ),
            clarification_history=(
                original_meta.get("clarification_history")
                if isinstance(original_meta.get("clarification_history"), list)
                else []
            ),
        )
        if isinstance(legacy_original_description, str) and legacy_original_description.strip():
            meta["original_user_store_description"] = legacy_original_description

    mode_from_draft = _infer_mode_from_draft_payload(draft_payload)
    if mode_from_draft == "clarification":
        expected_status = WORKFLOW_STATUS_NEEDS_CLARIFICATION
    elif mode_from_draft == "failed_recoverable":
        expected_status = WORKFLOW_STATUS_FAILED_RECOVERABLE
    else:
        expected_status = WORKFLOW_STATUS_READY_FOR_REVIEW
    expected_mode = mode_from_draft or "clarification"
    if expected_mode == "clarification":
        expected_step = "analyzing_description"
    elif expected_mode == "failed_recoverable":
        expected_step = "recoverable_failure"
    else:
        expected_step = "setting_up_store_configuration"

    status = _normalize_cached_workflow_status(meta.get("status"))
    if status is None:
        meta["status"] = expected_status
    elif status is not None:
        meta["status"] = status

    mode = meta.get("mode")
    if (
        not isinstance(mode, str)
        or mode not in {"clarification", "draft_ready", "failed_recoverable"}
    ):
        meta["mode"] = expected_mode

    current_step = meta.get("current_step")
    if not isinstance(current_step, str) or not current_step.strip():
        meta["current_step"] = expected_step

    if not isinstance(meta.get("is_fallback"), bool):
        meta["is_fallback"] = False

    if meta.get("status") == WORKFLOW_STATUS_READY_FOR_REVIEW:
        meta["is_fallback"] = False
        if meta.get("mode") != "draft_ready":
            meta["mode"] = "draft_ready"

    if meta.get("status") == WORKFLOW_STATUS_FAILED_RECOVERABLE:
        meta["is_fallback"] = True
        meta["mode"] = "failed_recoverable"
        meta["current_step"] = "recoverable_failure"
        meta.setdefault("error_code", RECOVERABLE_FAILURE_ERROR_CODE)
        meta.setdefault("user_message", RECOVERABLE_FAILURE_USER_MESSAGE)
        meta.setdefault("retry_allowed", True)
        meta.setdefault("manual_edit_allowed", True)

    if not isinstance(meta.get("clarification_history"), list):
        meta["clarification_history"] = []

    latest_input = meta.get("latest_clarification_input")
    if latest_input is not None and not isinstance(latest_input, str):
        meta["latest_clarification_input"] = str(latest_input)

    original_description = meta.get("original_user_store_description")
    if not isinstance(original_description, str) or not original_description.strip():
        fallback_description = _derive_original_description_fallback(
            store=store,
            draft_payload=draft_payload,
            draft_meta=meta,
        )
        if fallback_description:
            meta["original_user_store_description"] = fallback_description

    if meta != original_meta:
        save_ai_draft_meta(store.id, meta)
    return meta


def _build_recoverable_fallback_metadata(
    *,
    reason: str,
    original_user_store_description: str,
    error_code: str = RECOVERABLE_FAILURE_ERROR_CODE,
    user_message: str = RECOVERABLE_FAILURE_USER_MESSAGE,
    clarification_round_count: int | None = None,
    repair_attempt_count: int | None = None,
    latest_clarification_input: str | None = None,
    clarification_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _ = reason
    metadata = _build_recoverable_failure_metadata(
        error_code=error_code,
        user_message=user_message,
        clarification_round_count=clarification_round_count,
        repair_attempt_count=repair_attempt_count,
        latest_clarification_input=latest_clarification_input,
        clarification_history=clarification_history,
    )
    metadata["original_user_store_description"] = original_user_store_description
    return metadata


__all__ = [
    "_build_ready_for_review_metadata",
    "_build_recoverable_failure_metadata",
    "_build_recoverable_fallback_metadata",
    "_get_or_rebuild_draft_metadata",
    "_recoverable_error_code_for_exception",
    "_safe_non_negative_int",
    "_with_workflow_counter_metadata",
    "is_legacy_clarification_fallback",
]
