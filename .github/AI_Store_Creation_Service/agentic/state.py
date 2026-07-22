"""Typed state contracts for the future agentic AI Store Creation graph.

This module intentionally contains no graph execution, provider calls, Redis
access, or Django model imports. Graph state must stay JSON-serializable.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from ..constants import (
    WORKFLOW_STATUS_APPLIED,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
)


DetectedLanguage = Literal[
    "ar",
    "en",
    "unknown",
]




class StoreBlueprint(TypedDict):
    normalized_description: str
    product_offering: Any
    catalog_scope: Any
    target_audience: Any
    target_market: Any
    customer_problem: Any
    unique_value_proposition: Any
    price_positioning: Any
    brand_personality: Any
    visual_preferences: Any
    language: Literal["ar", "en"]
    currency: str
    category_strategy: str
    product_strategy: str
    customer_fit_strategy: str
    brand_voice_strategy: str
    pricing_strategy: str
    visual_strategy: str
    available_theme_templates: list[str]
    locked_constraints: dict[str, Any]
    source_context: dict[str, Any]


class ValidationIssue(TypedDict):
    path: str
    code: str
    message: str
    repairable: bool


WorkflowEntry = Literal[
    "fresh",
    "clarification_resume",
]


class ClarificationQuestion(TypedDict):
    question_id: str
    question_key: str
    target_fact: str
    question_text: str
    reason: str
    recommendation: str | None
    answer_type: Literal["single_select", "free_text"]
    options: list[str]
    other_option: str | None
    allow_custom_answer: bool
    required: bool


class ClarificationAnswer(TypedDict):
    question_key: str
    selected_option: str
    custom_answer: NotRequired[str]


class ClarificationRound(TypedDict):
    round_number: int
    questions: list[ClarificationQuestion]
    answers: list[ClarificationAnswer]
    resolved_facts: dict[str, str]


WorkflowMode = Literal[
    "clarification",
    "draft_ready",
    "failed_recoverable",
]

WorkflowStatus = Literal[
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_APPLIED,
]

RouteDecision = Literal[
    "clarify",
    "generate",
    "validate",
    "human_review",
    "failed_recoverable",
]

CurrentGraphStep = Literal[
    "merge_answers",
    "understand",
    "feedback",
    "decide",
    "clarify",
    "generate",
    "validate",
    "human_review",
    "recoverable_failure",
]


class AIStoreAgentState(TypedDict):
    # Identity and input. These are available after the legacy pre-graph setup.
    store_id: int
    tenant_id: int
    user_id: int
    user_store_description: str
    normalized_description: str

    # Context gathered by graph nodes.
    available_theme_templates: NotRequired[list[str]]

    # Deterministic understanding data.
    description_language: NotRequired[DetectedLanguage]
    description_word_count: NotRequired[int]
    detected_store_domains: NotRequired[list[str]]
    description_sufficient: NotRequired[bool]
    understanding_valid: NotRequired[bool]
    understanding_reasons: NotRequired[list[str]]
    target_audience: NotRequired[str]
    product_direction: NotRequired[list[str]]
    blocking_missing_information: NotRequired[list[str]]
    missing_information: NotRequired[list[str]]
    confidence_score: NotRequired[int]
    ambiguities: NotRequired[list[str]]
    description_personalization_facts: NotRequired[dict[str, Any]]
    missing_core_personalization_keys: NotRequired[list[str]]
    ambiguous_personalization_keys: NotRequired[list[str]]
    personalization_core_complete: NotRequired[bool]
    additional_blocking_missing_information: NotRequired[list[str]]
    effective_personalization_context: NotRequired[dict[str, Any]]
    personalization_progress: NotRequired[dict[str, Any]]
    blueprint: NotRequired[StoreBlueprint]
    feedback: NotRequired[dict[str, Any]]

    # Workflow data.
    workflow_entry: NotRequired[WorkflowEntry]
    draft_payload: NotRequired[dict[str, Any]]
    draft_metadata: NotRequired[dict[str, Any]]
    mode: NotRequired[WorkflowMode]
    status: NotRequired[WorkflowStatus]
    current_step: NotRequired[CurrentGraphStep]
    route_decision: NotRequired[RouteDecision]

    # Clarification.
    clarification_questions: NotRequired[list[ClarificationQuestion]]
    clarification_requested_keys: NotRequired[list[str]]
    clarification_question_specs: NotRequired[list[dict[str, str]]]
    clarification_answers: NotRequired[list[ClarificationAnswer]]
    clarification_history: NotRequired[list[ClarificationRound]]
    clarification_facts: NotRequired[dict[str, str]]
    merged_personalization_context: NotRequired[dict[str, str]]
    confirmed_personalization_context: NotRequired[dict[str, str]]
    answered_target_facts: NotRequired[list[str]]
    clarification_round_count: NotRequired[int]
    merge_valid: NotRequired[bool]

    # Repair and validation.
    repair_attempt_count: NotRequired[int]
    validation_errors: NotRequired[list[ValidationIssue]]

    # Safe failure data.
    error_code: NotRequired[str]
    user_message: NotRequired[str]


__all__ = [
    "AIStoreAgentState",
    "ClarificationAnswer",
    "ClarificationQuestion",
    "ClarificationRound",
    "CurrentGraphStep",
    "DetectedLanguage",
    "RouteDecision",
    "StoreBlueprint",
    "ValidationIssue",
    "WorkflowMode",
    "WorkflowStatus",
    "WorkflowEntry",
]
