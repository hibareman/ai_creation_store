"""Safe diagnostic helpers for Agentic generation failures."""

from __future__ import annotations

from typing import Any, Literal
from urllib.error import URLError


GenerationFailureCategory = Literal[
    "provider_factory",
    "provider_invocation",
    "provider_timeout",
    "response_parse",
    "response_schema",
    "blueprint_validation",
    "internal_error",
]

GenerationConstraintCode = Literal[
    "language_mismatch",
    "currency_mismatch",
    "unknown_generation_constraint",
    "not_applicable",
]

_GENERATION_FAILURE_CATEGORIES = frozenset(
    {
        "provider_factory",
        "provider_invocation",
        "provider_timeout",
        "response_parse",
        "response_schema",
        "blueprint_validation",
        "internal_error",
    }
)

_GENERATION_CONSTRAINT_CODES = frozenset(
    {
        "language_mismatch",
        "currency_mismatch",
        "unknown_generation_constraint",
        "not_applicable",
    }
)

GENERATION_FAILURE_LOG_MESSAGE = (
    "Agentic generation failed | store_id=%s | tenant_id=%s | step=%s "
    "| category=%s | constraint_code=%s | exception=%s"
)

_FAILURE_CATEGORY_ATTRIBUTE = "_agentic_generation_failure_category"
_FAILURE_CONSTRAINT_ATTRIBUTE = "_agentic_generation_constraint_code"
_FAILURE_LOGGED_ATTRIBUTE = "_agentic_generation_failure_logged"


class _SafeAgenticGenerationDiagnostic(Exception):
    """Redacted exception rendered by logger.exception()."""


def safe_identity_for_log(value: Any) -> int | str:
    """Return only a valid numeric identity or a non-sensitive marker."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return "invalid"
    return value


def safe_exception_class_name(exc: BaseException) -> str:
    """Return the exception type name without rendering its message."""

    return type(exc).__name__


def safe_exception_info(
    exc: BaseException,
) -> tuple[type[BaseException], BaseException, Any]:
    """Preserve the stack while replacing a potentially sensitive exception value."""

    redacted = _SafeAgenticGenerationDiagnostic(
        "Agentic generation exception details redacted."
    )
    return type(redacted), redacted, exc.__traceback__


def mark_failure_category(
    exc: BaseException,
    category: GenerationFailureCategory,
) -> GenerationFailureCategory:
    """Attach a safe category for an outer node boundary when possible."""

    try:
        setattr(exc, _FAILURE_CATEGORY_ATTRIBUTE, category)
    except Exception:
        pass
    return category


def failure_category(
    exc: BaseException,
    *,
    default: GenerationFailureCategory,
) -> GenerationFailureCategory:
    value = getattr(exc, _FAILURE_CATEGORY_ATTRIBUTE, None)
    if value in _GENERATION_FAILURE_CATEGORIES:
        return value
    return default


def mark_constraint_code(
    exc: BaseException,
    code: GenerationConstraintCode,
) -> GenerationConstraintCode:
    """Attach a non-sensitive constraint code to an exception."""

    normalized: GenerationConstraintCode = (
        code if code in _GENERATION_CONSTRAINT_CODES else "unknown_generation_constraint"
    )
    try:
        setattr(exc, _FAILURE_CONSTRAINT_ATTRIBUTE, normalized)
    except Exception:
        pass
    return normalized


def failure_constraint_code(
    exc: BaseException,
    *,
    default: GenerationConstraintCode = "not_applicable",
) -> GenerationConstraintCode:
    """Return a safe constraint code without reading the exception message."""

    value = getattr(exc, _FAILURE_CONSTRAINT_ATTRIBUTE, None)
    if value in _GENERATION_CONSTRAINT_CODES:
        return value

    public_value = getattr(exc, "constraint_code", None)
    if public_value in _GENERATION_CONSTRAINT_CODES:
        return public_value
    return default


def mark_failure_logged(exc: BaseException) -> None:
    """Mark an exception after its safe diagnostic has been emitted."""

    try:
        setattr(exc, _FAILURE_LOGGED_ATTRIBUTE, True)
    except Exception:
        pass


def failure_already_logged(exc: BaseException) -> bool:
    """Return whether this exact exception was already safely logged."""

    return getattr(exc, _FAILURE_LOGGED_ATTRIBUTE, False) is True


def is_timeout_failure(exc: BaseException) -> bool:
    """Detect timeout types through safe exception chaining without reading messages."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        if isinstance(current, URLError) and isinstance(current.reason, TimeoutError):
            return True
        if isinstance(current.__cause__, BaseException):
            pending.append(current.__cause__)
        if isinstance(current.__context__, BaseException):
            pending.append(current.__context__)
    return False


__all__ = [
    "GENERATION_FAILURE_LOG_MESSAGE",
    "GenerationConstraintCode",
    "GenerationFailureCategory",
    "failure_already_logged",
    "failure_category",
    "failure_constraint_code",
    "is_timeout_failure",
    "mark_constraint_code",
    "mark_failure_category",
    "mark_failure_logged",
    "safe_exception_class_name",
    "safe_exception_info",
    "safe_identity_for_log",
]