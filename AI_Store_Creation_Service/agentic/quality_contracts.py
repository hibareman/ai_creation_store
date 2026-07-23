"""Strict internal contracts for semantic quality review state and output."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..constants import (
    MAX_QUALITY_ISSUES,
    MAX_QUALITY_ISSUE_PATH_LENGTH,
    MAX_QUALITY_ISSUE_TEXT_LENGTH,
    MAX_QUALITY_REVISIONS,
    MIN_QUALITY_PASS_SCORE,
    QUALITY_REVIEW_STATUSES,
    QUALITY_REVIEW_STATUS_NOT_STARTED,
    QUALITY_REVIEW_STATUS_PASSED,
    QUALITY_REVIEW_STATUS_REVISION_APPLIED,
    QUALITY_REVIEW_STATUS_REVISION_REQUIRED,
)
from .state import QUALITY_CRITERIA, QUALITY_ISSUE_SEVERITIES


QUALITY_STATE_FIELDS = frozenset(
    {
        "quality_review_status",
        "quality_score",
        "quality_issues",
        "quality_revision_count",
    }
)
QUALITY_ISSUE_ROOT_PATHS = frozenset(
    {
        "draft_payload",
        "store",
        "store_settings",
        "theme",
        "categories",
        "products",
        "ai_analysis",
    }
)


class AIQualityReviewContractError(ValueError):
    """Raised when reviewer output violates the internal quality contract."""


def quality_state_defaults() -> dict[str, Any]:
    return {
        "quality_review_status": QUALITY_REVIEW_STATUS_NOT_STARTED,
        "quality_score": None,
        "quality_issues": [],
        "quality_revision_count": 0,
    }


def set_quality_state_defaults(state: dict[str, Any]) -> None:
    """Upgrade pre-quality cached state without repairing partial bad state."""

    if QUALITY_STATE_FIELDS.intersection(state):
        return
    state.update(quality_state_defaults())


def validate_quality_review_payload(value: Any) -> dict[str, Any]:
    """Validate exact provider output and derive status deterministically."""

    if not isinstance(value, Mapping) or set(value) != {"score", "issues"}:
        raise AIQualityReviewContractError(
            "Quality review must contain exactly score and issues."
        )
    score = _validate_score(value.get("score"))
    raw_issues = value.get("issues")
    if not isinstance(raw_issues, list) or len(raw_issues) > MAX_QUALITY_ISSUES:
        raise AIQualityReviewContractError(
            "Quality review issues must be a bounded list."
        )

    issues = [validate_quality_issue(issue) for issue in raw_issues]
    _reject_duplicate_issues(issues)
    severities = {issue["severity"] for issue in issues}
    if "high" in severities and score > 59:
        raise AIQualityReviewContractError(
            "A high-severity issue requires a score of 59 or lower."
        )
    if "high" not in severities and "medium" in severities and score > 79:
        raise AIQualityReviewContractError(
            "A medium-severity issue requires a score of 79 or lower."
        )

    passed = (
        score >= MIN_QUALITY_PASS_SCORE
        and not severities.intersection({"high", "medium"})
    )
    if not passed and not issues:
        raise AIQualityReviewContractError(
            "A revision-required review must contain an actionable issue."
        )
    return {
        "quality_review_status": (
            QUALITY_REVIEW_STATUS_PASSED
            if passed
            else QUALITY_REVIEW_STATUS_REVISION_REQUIRED
        ),
        "quality_score": score,
        "quality_issues": issues,
        "quality_revision_count": 0,
    }


def validate_quality_issue(value: Any) -> dict[str, str]:
    required_fields = {
        "path",
        "criterion",
        "severity",
        "problem",
        "instruction",
    }
    if not isinstance(value, Mapping) or set(value) != required_fields:
        raise AIQualityReviewContractError(
            "Quality issue fields do not match the contract."
        )

    path = _normalize_issue_text(
        value.get("path"),
        field_name="path",
        max_length=MAX_QUALITY_ISSUE_PATH_LENGTH,
        collapse_whitespace=False,
    )
    if any(character.isspace() for character in path):
        raise AIQualityReviewContractError(
            "Quality issue path must not contain whitespace."
        )
    root_path = path.split(".", 1)[0].split("[", 1)[0]
    if root_path not in QUALITY_ISSUE_ROOT_PATHS:
        raise AIQualityReviewContractError(
            "Quality issue path targets an unsupported draft section."
        )

    criterion = value.get("criterion")
    severity = value.get("severity")
    if not isinstance(criterion, str) or criterion not in QUALITY_CRITERIA:
        raise AIQualityReviewContractError(
            "Quality issue criterion is unsupported."
        )
    if (
        not isinstance(severity, str)
        or severity not in QUALITY_ISSUE_SEVERITIES
    ):
        raise AIQualityReviewContractError(
            "Quality issue severity is unsupported."
        )
    return {
        "path": path,
        "criterion": criterion,
        "severity": severity,
        "problem": _normalize_issue_text(
            value.get("problem"),
            field_name="problem",
            max_length=MAX_QUALITY_ISSUE_TEXT_LENGTH,
        ),
        "instruction": _normalize_issue_text(
            value.get("instruction"),
            field_name="instruction",
            max_length=MAX_QUALITY_ISSUE_TEXT_LENGTH,
        ),
    }


def has_valid_quality_review_state(state: Mapping[str, Any]) -> bool:
    if QUALITY_STATE_FIELDS.intersection(state) != QUALITY_STATE_FIELDS:
        return False

    status = state.get("quality_review_status")
    score = state.get("quality_score")
    issues = state.get("quality_issues")
    revision_count = state.get("quality_revision_count")
    if not isinstance(status, str) or status not in QUALITY_REVIEW_STATUSES:
        return False
    if score is not None and _safe_quality_score(score) is None:
        return False
    if (
        not isinstance(issues, list)
        or len(issues) > MAX_QUALITY_ISSUES
        or not _all_quality_issues_valid(issues)
    ):
        return False
    if (
        not _is_non_negative_int(revision_count)
        or revision_count > MAX_QUALITY_REVISIONS
    ):
        return False

    if status == QUALITY_REVIEW_STATUS_NOT_STARTED:
        return score is None and issues == [] and revision_count == 0
    if status == QUALITY_REVIEW_STATUS_REVISION_APPLIED:
        return (
            score is None
            and issues == []
            and revision_count == MAX_QUALITY_REVISIONS
        )
    if (
        status
        not in {
            QUALITY_REVIEW_STATUS_PASSED,
            QUALITY_REVIEW_STATUS_REVISION_REQUIRED,
        }
        or revision_count != 0
    ):
        return False
    try:
        normalized_review = validate_quality_review_payload(
            {"score": score, "issues": issues}
        )
    except AIQualityReviewContractError:
        return False
    return normalized_review["quality_review_status"] == status


def safe_quality_state(source: Mapping[str, Any]) -> dict[str, Any]:
    try:
        if has_valid_quality_review_state(source):
            return {
                "quality_review_status": source["quality_review_status"],
                "quality_score": source["quality_score"],
                "quality_issues": [
                    validate_quality_issue(deepcopy(issue))
                    for issue in source["quality_issues"]
                ],
                "quality_revision_count": source["quality_revision_count"],
            }
    except Exception:
        pass
    return quality_state_defaults()


def _validate_score(value: Any) -> int:
    score = _safe_quality_score(value)
    if score is None:
        raise AIQualityReviewContractError(
            "Quality score must be an integer from 0 to 100."
        )
    return score


def _safe_quality_score(value: Any) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 100
    ):
        return value
    return None


def _normalize_issue_text(
    value: Any,
    *,
    field_name: str,
    max_length: int,
    collapse_whitespace: bool = True,
) -> str:
    if not isinstance(value, str):
        raise AIQualityReviewContractError(
            f"Quality issue {field_name} must be text."
        )
    normalized = (
        " ".join(value.strip().split())
        if collapse_whitespace
        else value.strip()
    )
    if not normalized or len(normalized) > max_length:
        raise AIQualityReviewContractError(
            f"Quality issue {field_name} has an invalid length."
        )
    return normalized


def _reject_duplicate_issues(issues: list[dict[str, str]]) -> None:
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        identity = (issue["path"].casefold(), issue["criterion"])
        if identity in seen:
            raise AIQualityReviewContractError(
                "Quality review contains duplicate issues."
            )
        seen.add(identity)


def _all_quality_issues_valid(issues: list[Any]) -> bool:
    try:
        normalized = [validate_quality_issue(issue) for issue in issues]
        _reject_duplicate_issues(normalized)
    except AIQualityReviewContractError:
        return False
    return True


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = [
    "AIQualityReviewContractError",
    "QUALITY_ISSUE_ROOT_PATHS",
    "QUALITY_STATE_FIELDS",
    "has_valid_quality_review_state",
    "quality_state_defaults",
    "safe_quality_state",
    "set_quality_state_defaults",
    "validate_quality_issue",
    "validate_quality_review_payload",
]
