"""Provider-backed semantic review for technically valid Agentic drafts."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ..exceptions import AIProviderParsingError
from ..parsers import parse_provider_raw_response_to_dict
from ..providers import AIProviderContract, get_ai_provider_client
from .quality_contracts import (
    AIQualityReviewContractError,
    validate_quality_review_payload,
)

logger = logging.getLogger(__name__)

_MAX_PROVIDER_ATTEMPTS = 2


class AIConsultantReviewError(ValueError):
    """Raised when a semantic review cannot produce a safe quality result."""


def review_generated_store_draft(
    *,
    tenant_id: Any,
    store_id: Any,
    normalized_description: Any,
    clarification_facts: Any,
    effective_personalization_context: Any,
    blueprint: Any,
    draft_payload: Any,
    provider: AIProviderContract | None = None,
) -> dict[str, Any]:
    """Review one validated draft and return normalized internal quality state."""

    normalized_tenant_id = _validate_positive_int(
        tenant_id,
        field_name="tenant_id",
    )
    normalized_store_id = _validate_positive_int(
        store_id,
        field_name="store_id",
    )
    description = _validate_description(normalized_description)
    facts = _validate_mapping(
        clarification_facts,
        field_name="clarification_facts",
        allow_empty=True,
    )
    context = _validate_mapping(
        effective_personalization_context,
        field_name="effective_personalization_context",
    )
    normalized_blueprint = _validate_mapping(
        blueprint,
        field_name="blueprint",
    )
    normalized_draft = _validate_mapping(
        draft_payload,
        field_name="draft_payload",
    )
    ai_provider = provider or get_ai_provider_client()

    last_contract_error: Exception | None = None
    for attempt_number in range(1, _MAX_PROVIDER_ATTEMPTS + 1):
        try:
            raw_response = ai_provider.review_agentic_store_draft(
                tenant_id=normalized_tenant_id,
                store_id=normalized_store_id,
                normalized_description=description,
                clarification_facts=deepcopy(facts),
                effective_personalization_context=deepcopy(context),
                blueprint=deepcopy(normalized_blueprint),
                draft_payload=deepcopy(normalized_draft),
                contract_retry=attempt_number > 1,
            )
        except Exception as exc:
            logger.exception(
                "Agentic consultant provider call failed | "
                "tenant_id=%s | store_id=%s | error_type=%s",
                normalized_tenant_id,
                normalized_store_id,
                type(exc).__name__,
            )
            raise AIConsultantReviewError(
                "Consultant review provider is unavailable."
            ) from exc
        try:
            parsed_payload = parse_provider_raw_response_to_dict(raw_response)
            return validate_quality_review_payload(parsed_payload)
        except (AIProviderParsingError, AIQualityReviewContractError) as exc:
            last_contract_error = exc
            logger.warning(
                "Agentic consultant review response rejected | "
                "tenant_id=%s | store_id=%s | attempt=%s | error_type=%s",
                normalized_tenant_id,
                normalized_store_id,
                attempt_number,
                type(exc).__name__,
            )

    raise AIConsultantReviewError(
        "Consultant review did not return a valid quality result."
    ) from last_contract_error


def _validate_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AIConsultantReviewError(
            f"{field_name} must be a positive integer."
        )
    return value


def _validate_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIConsultantReviewError(
            "normalized_description must be non-empty text."
        )
    return " ".join(value.strip().split())


def _validate_mapping(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AIConsultantReviewError(f"{field_name} must be an object.")
    normalized = dict(deepcopy(value))
    if not allow_empty and not normalized:
        raise AIConsultantReviewError(f"{field_name} must not be empty.")
    try:
        json.dumps(normalized, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AIConsultantReviewError(
            f"{field_name} must be JSON-serializable."
        ) from exc
    return normalized


__all__ = [
    "AIConsultantReviewError",
    "review_generated_store_draft",
]
