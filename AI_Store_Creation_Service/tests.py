import inspect
import importlib
import json
import sys
from copy import deepcopy
from importlib.metadata import version as package_version
from typing import Any, get_args
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from langgraph.graph import END, START, StateGraph

from categories.models import Category
from products.models import Inventory, Product, ProductImage
from stores.models import Store, StoreSettings
from themes.models import StoreThemeConfig, ThemeTemplate

from . import (
    agentic_production_services,
    agentic_session_services,
    agentic_state_store,
    apply_services,
    metadata_services,
    services,
    workflow_services,
)
from .agentic import feature_flags, generation, merging, repairing, routing, runner, understanding, validation, clarifying
from .agentic.feature_flags import is_agentic_workflow_enabled
from .agentic.graph import build_agentic_graph, compile_agentic_graph
from .agentic.nodes import (
    blueprint_node,
    clarify_node,
    decide_node,
    generate_node,
    human_review_node,
    merge_answers_node,
    recoverable_failure_node,
    repair_node,
    understand_node,
    validate_node,
)
from .agentic.routing import (
    route_after_decide,
    route_after_generate,
    route_after_merge,
    route_after_repair,
    route_after_validate,
    route_workflow_entry,
)
from .agentic.runner import (
    build_initial_agent_state,
    build_safe_agentic_failure_state,
    resume_agentic_workflow,
    run_agentic_workflow,
    validate_agentic_terminal_state,
)
from .agentic.state import (
    AIStoreAgentState,
    ClarificationAnswer,
    ClarificationRound,
    CurrentGraphStep,
    DetectedLanguage,
    RouteDecision,
    ValidationIssue,
    WorkflowMode,
    WorkflowStatus,
    WorkflowEntry,
)
from .draft_store import get_ai_draft, get_ai_draft_meta, save_ai_draft, save_ai_draft_meta
from .constants import (
    AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE,
    CATEGORY_APPLY_FAILED_USER_MESSAGE,
    AI_AGENTIC_STATE_MAX_BYTES,
    AI_AGENTIC_STATE_SCHEMA_VERSION,
    MAX_CLARIFICATION_ROUNDS,
    MAX_REPAIR_ATTEMPTS,
    LAST_OPERATION_PARTIAL_REGENERATION,
    LAST_OPERATION_STATUS_COMPLETED,
    PARTIAL_REGENERATION_FAILED_ERROR_CODE,
    PARTIAL_REGENERATION_FAILED_USER_MESSAGE,
    PRODUCT_APPLY_FAILED_USER_MESSAGE,
    RECOVERABLE_FAILURE_ERROR_CODE,
    RECOVERABLE_FAILURE_USER_MESSAGE,
    STORE_CORE_APPLY_FAILED_USER_MESSAGE,
    THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE,
    THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE,
    WORKFLOW_STATUS_APPLIED,
    WORKFLOW_STATUS_FAILED_RECOVERABLE,
    WORKFLOW_STATUS_NEEDS_CLARIFICATION,
    WORKFLOW_STATUS_PROCESSING,
    WORKFLOW_STATUS_READY_FOR_REVIEW,
    build_ai_agentic_state_key,
    build_ai_draft_key,
    build_ai_draft_meta_key,
)
from .agentic_session_services import (
    delete_cached_agentic_workflow,
    get_cached_agentic_workflow,
    resume_cached_agentic_workflow,
    start_cached_agentic_workflow,
)
from .agentic_state_store import (
    AgenticStateStoreError,
    delete_agentic_workflow_state,
    get_agentic_workflow_state,
    save_agentic_workflow_state,
)
from .models import AIStoreAuditLog
from .prompts import (
    build_analyze_store_description_messages,
    build_generate_agentic_store_draft_messages,
    build_clarify_store_draft_messages,
    build_generate_clarification_questions_messages,
    build_generate_store_draft_messages,
)
from .providers import AIProviderContract, OllamaProviderClient, get_ai_provider_client
from .selectors import get_store_for_ai_flow, get_store_settings_for_ai_flow
from .services import (
    apply_current_ai_draft_categories,
    apply_current_ai_draft_products,
    apply_current_ai_draft_store_core,
    apply_current_ai_draft_to_store,
    create_draft_store_for_ai_flow,
    derive_store_name_from_description,
    generate_initial_store_draft,
    get_current_ai_draft,
    process_clarification_round,
    regenerate_store_draft,
    regenerate_store_draft_section,
    start_ai_draft_workflow,
)
from .validators import build_ai_recoverable_failure_payload, validate_initial_description

User = get_user_model()


class AIAgenticStateFoundationTests(SimpleTestCase):
    def test_agent_state_can_be_constructed_with_startup_identity_and_description(self):
        state: AIStoreAgentState = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a modern fashion store for women",
            "normalized_description": "Create a modern fashion store for women",
        }

        self.assertEqual(state["store_id"], 10)
        self.assertEqual(state["tenant_id"], 101)
        self.assertEqual(state["user_id"], 7)
        self.assertEqual(
            state["normalized_description"],
            "Create a modern fashion store for women",
        )

    def test_agent_state_values_are_plain_json_serializable_data(self):
        issue: ValidationIssue = {
            "path": "products.0.price",
            "code": "invalid_price",
            "message": "Product price must be positive.",
            "repairable": True,
        }
        state: AIStoreAgentState = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a modern fashion store for women",
            "normalized_description": "Create a modern fashion store for women",
            "available_theme_templates": ["Modern", "Classic"],
            "draft_payload": {"store": {"name": "Fashion Store"}},
            "draft_metadata": {"status": WORKFLOW_STATUS_READY_FOR_REVIEW},
            "mode": "draft_ready",
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": "human_review",
            "route_decision": "human_review",
            "clarification_questions": [],
            "clarification_round_count": 0,
            "repair_attempt_count": 0,
            "validation_errors": [issue],
            "description_language": "en",
            "description_word_count": 7,
            "detected_store_domains": ["fashion"],
            "description_sufficient": True,
            "understanding_valid": True,
            "understanding_reasons": ["sufficient_business_direction"],
            "business_summary": "A fashion store.",
            "target_audience": "women",
            "product_direction": ["clothing"],
            "blocking_missing_information": [],
            "ambiguities": [],
            "error_code": "",
            "user_message": "",
        }

        serialized = json.dumps(state)

        self.assertIn("Fashion Store", serialized)

    def test_validation_issue_has_expected_required_structure(self):
        expected_keys = frozenset({"path", "code", "message", "repairable"})

        self.assertEqual(ValidationIssue.__required_keys__, expected_keys)
        self.assertEqual(ValidationIssue.__optional_keys__, frozenset())

    def test_agent_state_does_not_require_django_model_objects(self):
        state: AIStoreAgentState = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a modern fashion store for women",
            "normalized_description": "Create a modern fashion store for women",
        }

        self.assertIsInstance(state, dict)
        self.assertNotIn("store", state)
        self.assertNotIn("user", state)
        self.assertNotIn("provider", state)

    def test_agentic_literal_values_match_phase_one_contract(self):
        self.assertEqual(
            set(get_args(WorkflowStatus)),
            {
                WORKFLOW_STATUS_PROCESSING,
                WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                WORKFLOW_STATUS_READY_FOR_REVIEW,
                WORKFLOW_STATUS_FAILED_RECOVERABLE,
                WORKFLOW_STATUS_APPLIED,
            },
        )
        self.assertEqual(
            set(get_args(DetectedLanguage)),
            {"ar", "en", "unknown"},
        )
        self.assertEqual(
            set(get_args(WorkflowMode)),
            {"clarification", "draft_ready", "failed_recoverable"},
        )
        self.assertEqual(
            set(get_args(RouteDecision)),
            {
                "clarify",
                "blueprint",
                "generate",
                "validate",
                "repair",
                "human_review",
                "failed_recoverable",
            },
        )
        self.assertEqual(
            set(get_args(CurrentGraphStep)),
            {
                "merge_answers",
                "understand",
                "merge_answers",
                "decide",
                "clarify",
                "blueprint",
                "generate",
                "validate",
                "repair",
                "human_review",
                "recoverable_failure",
            },
        )
        self.assertEqual(set(get_args(WorkflowEntry)), {"fresh", "clarification_resume"})


class AIAgenticRoutingFoundationTests(SimpleTestCase):
    def test_feature_flag_defaults_to_false(self):
        self.assertFalse(is_agentic_workflow_enabled())

        with patch.object(feature_flags, "settings", object()):
            self.assertFalse(is_agentic_workflow_enabled())

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=True)
    def test_feature_flag_returns_true_when_enabled(self):
        self.assertTrue(is_agentic_workflow_enabled())
        self.assertIs(is_agentic_workflow_enabled(), True)

    def test_route_after_decide_supports_clarify_and_blueprint(self):
        self.assertEqual(
            route_after_decide({"route_decision": "clarify"}),
            "clarify",
        )
        self.assertEqual(
            route_after_decide({"route_decision": "blueprint"}),
            "blueprint",
        )

    def test_route_after_decide_unknown_or_missing_routes_fail_closed(self):
        self.assertEqual(
            route_after_decide({"route_decision": "generate"}),
            "failed_recoverable",
        )
        self.assertEqual(route_after_decide({}), "failed_recoverable")
        self.assertEqual(route_after_decide({"route_decision": None}), "failed_recoverable")

    def test_route_workflow_entry_supports_fresh_and_resume_only(self):
        self.assertEqual(route_workflow_entry({"workflow_entry": "fresh"}), "understand")
        self.assertEqual(
            route_workflow_entry({"workflow_entry": "clarification_resume"}),
            "merge_answers",
        )

        for workflow_entry in ("unknown", "", None, True, False, 1):
            with self.subTest(workflow_entry=workflow_entry):
                self.assertEqual(
                    route_workflow_entry({"workflow_entry": workflow_entry}),
                    "failed_recoverable",
                )
        self.assertEqual(route_workflow_entry({}), "failed_recoverable")

    def test_route_after_merge_requires_valid_merge_step_and_processing_status(self):
        self.assertEqual(
            route_after_merge(
                {
                    "current_step": "merge_answers",
                    "merge_valid": True,
                    "status": WORKFLOW_STATUS_PROCESSING,
                }
            ),
            "understand",
        )

        invalid_states = (
            {"current_step": "merge_answers", "merge_valid": False, "status": WORKFLOW_STATUS_PROCESSING},
            {"current_step": "merge_answers", "status": WORKFLOW_STATUS_PROCESSING},
            {"current_step": "understand", "merge_valid": True, "status": WORKFLOW_STATUS_PROCESSING},
            {"current_step": "merge_answers", "merge_valid": True, "status": WORKFLOW_STATUS_FAILED_RECOVERABLE},
            {"current_step": "merge_answers", "merge_valid": "true", "status": WORKFLOW_STATUS_PROCESSING},
            {},
        )
        for state in invalid_states:
            with self.subTest(state=state):
                self.assertEqual(route_after_merge(state), "failed_recoverable")

    def test_route_after_validate_routes_successful_validation_to_human_review(self):
        self.assertEqual(
            route_after_validate({"route_decision": "human_review"}),
            "human_review",
        )

    def test_route_after_validate_allows_repair_only_below_limit(self):
        self.assertEqual(
            route_after_validate(
                {
                    "route_decision": "repair",
                    "repair_attempt_count": 0,
                }
            ),
            "repair",
        )
        self.assertEqual(
            route_after_validate(
                {
                    "route_decision": "repair",
                    "repair_attempt_count": MAX_REPAIR_ATTEMPTS - 1,
                }
            ),
            "repair",
        )

    def test_route_after_validate_repair_at_or_above_limit_fails_closed(self):
        self.assertEqual(
            route_after_validate(
                {
                    "route_decision": "repair",
                    "repair_attempt_count": MAX_REPAIR_ATTEMPTS,
                }
            ),
            "failed_recoverable",
        )
        self.assertEqual(
            route_after_validate(
                {
                    "route_decision": "repair",
                    "repair_attempt_count": MAX_REPAIR_ATTEMPTS + 1,
                }
            ),
            "failed_recoverable",
        )
        self.assertEqual(
            route_after_validate(
                {
                    "route_decision": "repair",
                    "repair_attempt_count": "1",
                }
            ),
            "failed_recoverable",
        )

    def test_route_after_validate_unknown_or_missing_routes_fail_closed(self):
        self.assertEqual(
            route_after_validate({"route_decision": "blueprint"}),
            "failed_recoverable",
        )
        self.assertEqual(route_after_validate({}), "failed_recoverable")

    def test_route_after_repair_returns_validate_only_for_valid_counter_values(self):
        self.assertEqual(
            route_after_repair(
                {
                    "route_decision": "validate",
                    "repair_attempt_count": 1,
                }
            ),
            "validate",
        )
        self.assertEqual(
            route_after_repair(
                {
                    "route_decision": "validate",
                    "repair_attempt_count": MAX_REPAIR_ATTEMPTS,
                }
            ),
            "validate",
        )

        for invalid_count in (0, -1, MAX_REPAIR_ATTEMPTS + 1, None, "1", True):
            with self.subTest(invalid_count=invalid_count):
                self.assertEqual(
                    route_after_repair(
                        {
                            "route_decision": "validate",
                            "repair_attempt_count": invalid_count,
                        }
                    ),
                    "failed_recoverable",
                )

        for route_decision in ("failed_recoverable", "repair", "unknown", None):
            with self.subTest(route_decision=route_decision):
                self.assertEqual(
                    route_after_repair(
                        {
                            "route_decision": route_decision,
                            "repair_attempt_count": 1,
                        }
                    ),
                    "failed_recoverable",
                )
        self.assertEqual(route_after_repair({"repair_attempt_count": 1}), "failed_recoverable")

    def test_routing_functions_do_not_mutate_input_state(self):
        state: AIStoreAgentState = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a modern fashion store for women",
            "normalized_description": "Create a modern fashion store for women",
            "route_decision": "repair",
            "repair_attempt_count": 1,
            "draft_payload": {"store": {"name": "Fashion Store"}},
        }
        before = json.dumps(state, sort_keys=True)

        route_after_decide(state)
        route_workflow_entry(state)
        route_after_merge(state)
        route_after_validate(state)
        route_after_repair(state)

        self.assertEqual(json.dumps(state, sort_keys=True), before)

    def test_routing_contracts_do_not_depend_on_provider_redis_models_or_workflows(self):
        routing_source = inspect.getsource(routing)

        for forbidden_reference in (
            "providers",
            "draft_store",
            "models",
            "apply_services",
            "workflow_services",
            "get_ai_provider_client",
            "save_ai_draft",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, routing_source)

        plain_state = {"route_decision": "blueprint"}
        self.assertEqual(route_after_decide(plain_state), "blueprint")

    def test_agentic_production_routing_is_limited_to_services_facade(self):
        services_source = inspect.getsource(services)
        workflow_source = inspect.getsource(workflow_services)

        self.assertIn("is_agentic_workflow_enabled", services_source)
        self.assertNotIn("is_agentic_workflow_enabled", workflow_source)
        self.assertNotIn("route_after_", services_source)
        self.assertNotIn("route_after_", workflow_source)
        self.assertNotIn("agentic_session_services", workflow_source)


class AIAgenticMergeAnswersTests(SimpleTestCase):
    @staticmethod
    def _question(
        question_key="primary_store_domain",
        question_text="What type of store should be created?",
        options=None,
    ):
        return {
            "question_key": question_key,
            "question_text": question_text,
            "options": options or ["Fashion Store", "Coffee Shop"],
        }

    @staticmethod
    def _answer(question_key="primary_store_domain", selected_option="Fashion Store"):
        return {
            "question_key": question_key,
            "selected_option": selected_option,
        }

    def _terminal_state(self, **overrides):
        questions = deepcopy(
            overrides.pop("clarification_questions", [self._question()])
        )
        state = {
            "workflow_entry": "clarification_resume",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "I want an online store",
            "normalized_description": "I want an online store",
            "current_step": "human_review",
            "mode": "clarification",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "route_decision": "human_review",
            "description_sufficient": False,
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "clarification_questions": questions,
            "clarification_answers": [self._answer()],
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": deepcopy(questions),
            },
            "validation_errors": [],
            "repair_attempt_count": 0,
        }
        state.update(overrides)
        return state

    def test_merge_canonicalizes_options_and_preserves_inputs(self):
        questions = [self._question()]
        answers = [self._answer(selected_option=" fashion   store ")]
        questions_before = deepcopy(questions)
        answers_before = deepcopy(answers)

        result = merging.merge_clarification_answers(
            clarification_questions=questions,
            clarification_answers=answers,
            clarification_history=[],
            clarification_facts={},
            clarification_round_count=0,
        )

        self.assertEqual(result["clarification_round_count"], 1)
        self.assertEqual(
            result["canonical_answers"],
            [self._answer(selected_option="Fashion Store")],
        )
        self.assertEqual(result["clarification_facts"], {"primary_store_domain": "Fashion Store"})
        self.assertEqual(result["clarification_history"][0]["round_number"], 1)
        self.assertEqual(
            result["clarification_history"][0]["resolved_facts"],
            {"primary_store_domain": "Fashion Store"},
        )
        self.assertEqual(questions, questions_before)
        self.assertEqual(answers, answers_before)
        json.dumps(result)

    def test_exact_answer_contract_rejects_malformed_or_unknown_answers(self):
        questions = [self._question()]
        circular = []
        circular.append(circular)
        invalid_answers = (
            "not-list",
            [],
            [{"question_key": "primary_store_domain"}],
            [{"selected_option": "Fashion Store"}],
            [{"question_key": "primary_store_domain", "selected_option": "Fashion Store", "extra": "x"}],
            [{"question_key": "unknown_key", "selected_option": "Fashion Store"}],
            [{"question_key": "primary_store_domain", "selected_option": "Sports"}],
            [{"question_key": "primary_store_domain", "selected_option": None}],
            [{"question_key": "primary_store_domain", "selected_option": {"value": "Fashion Store"}}],
            circular,
        )

        for answers in invalid_answers:
            with self.subTest(answers=answers):
                with self.assertRaises((merging.AIMergeValidationError, TypeError, ValueError)):
                    merging.merge_clarification_answers(
                        clarification_questions=questions,
                        clarification_answers=answers,
                        clarification_history=[],
                        clarification_facts={},
                        clarification_round_count=0,
                    )

    def test_all_questions_must_be_answered_and_order_can_vary(self):
        questions = [
            self._question("primary_store_domain", options=["Fashion", "Coffee"]),
            self._question(
                "target_audience",
                "Who is the target audience?",
                ["Students", "Professionals"],
            ),
        ]

        invalid_answers = (
            [self._answer("primary_store_domain", "Fashion")],
            [
                self._answer("primary_store_domain", "Fashion"),
                self._answer("target_audience", "Students"),
                self._answer("extra_key", "Extra"),
            ],
            [
                self._answer("primary_store_domain", "Fashion"),
                self._answer("primary_store_domain", "Coffee"),
            ],
        )
        for answers in invalid_answers:
            with self.subTest(answers=answers):
                with self.assertRaises(merging.AIMergeValidationError):
                    merging.merge_clarification_answers(
                        clarification_questions=questions,
                        clarification_answers=answers,
                        clarification_history=[],
                        clarification_facts={},
                        clarification_round_count=0,
                    )

        result = merging.merge_clarification_answers(
            clarification_questions=questions,
            clarification_answers=[
                self._answer("target_audience", " professionals "),
                self._answer("primary_store_domain", " coffee "),
            ],
            clarification_history=[],
            clarification_facts={},
            clarification_round_count=0,
        )

        self.assertEqual(
            result["clarification_facts"],
            {
                "target_audience": "Professionals",
                "primary_store_domain": "Coffee",
            },
        )

    def test_history_and_facts_are_validated_and_accumulate(self):
        first = merging.merge_clarification_answers(
            clarification_questions=[
                self._question("primary_store_domain", options=["Fashion", "Coffee"])
            ],
            clarification_answers=[self._answer("primary_store_domain", "Coffee")],
            clarification_history=[],
            clarification_facts={},
            clarification_round_count=0,
        )
        second = merging.merge_clarification_answers(
            clarification_questions=[
                self._question(
                    "product_direction",
                    "What products should be sold?",
                    ["Beans", "Drinks"],
                )
            ],
            clarification_answers=[self._answer("product_direction", "beans")],
            clarification_history=first["clarification_history"],
            clarification_facts=first["clarification_facts"],
            clarification_round_count=1,
        )

        self.assertEqual(second["clarification_round_count"], 2)
        self.assertEqual(
            [round_item["round_number"] for round_item in second["clarification_history"]],
            [1, 2],
        )
        self.assertEqual(
            second["clarification_facts"],
            {"primary_store_domain": "Coffee", "product_direction": "Beans"},
        )

        with self.assertRaises(merging.AIMergeValidationError):
            merging.merge_clarification_answers(
                clarification_questions=[self._question("product_direction")],
                clarification_answers=[self._answer("product_direction", "Fashion Store")],
                clarification_history=first["clarification_history"],
                clarification_facts={},
                clarification_round_count=1,
            )

        tampered_history = deepcopy(first["clarification_history"])
        tampered_history[0]["round_number"] = 2
        with self.assertRaises(merging.AIMergeValidationError):
            merging.merge_clarification_answers(
                clarification_questions=[self._question("product_direction")],
                clarification_answers=[self._answer("product_direction", "Fashion Store")],
                clarification_history=tampered_history,
                clarification_facts=first["clarification_facts"],
                clarification_round_count=1,
            )

    def test_merge_counter_increments_only_after_successful_validation(self):
        state = self._terminal_state()
        before = deepcopy(state)

        update = merge_answers_node(state)

        self.assertEqual(update["current_step"], "merge_answers")
        self.assertEqual(update["status"], WORKFLOW_STATUS_PROCESSING)
        self.assertTrue(update["merge_valid"])
        self.assertEqual(update["clarification_round_count"], 1)
        self.assertEqual(update["clarification_facts"], {"primary_store_domain": "Fashion Store"})
        self.assertEqual(update["clarification_questions"], [])
        self.assertEqual(update["clarification_answers"], [])
        self.assertEqual(state, before)

        failure = merge_answers_node(
            self._terminal_state(clarification_answers=[self._answer(selected_option="Sports")])
        )
        self.assertEqual(failure["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertFalse(failure["merge_valid"])
        self.assertEqual(failure["clarification_round_count"], 0)

    def test_merge_rejects_prior_count_at_limit_before_ai_boundary(self):
        questions = [self._question()]
        history = []
        facts = {}
        for count in range(MAX_CLARIFICATION_ROUNDS):
            result = merging.merge_clarification_answers(
                clarification_questions=questions,
                clarification_answers=[self._answer()],
                clarification_history=history,
                clarification_facts=facts,
                clarification_round_count=count,
            )
            history = result["clarification_history"]
            facts = result["clarification_facts"]

        with self.assertRaises(merging.AIMergeValidationError):
            merging.merge_clarification_answers(
                clarification_questions=questions,
                clarification_answers=[self._answer()],
                clarification_history=history,
                clarification_facts=facts,
                clarification_round_count=MAX_CLARIFICATION_ROUNDS,
            )

    def test_merge_source_boundaries_remain_deterministic(self):
        merge_node_module = importlib.import_module(
            "AI_Store_Creation_Service.agentic.nodes.merge_answers"
        )
        source = inspect.getsource(merging) + inspect.getsource(merge_node_module)

        for forbidden_reference in (
            "get_ai_provider_client",
            "providers",
            "prompts",
            "requests",
            "draft_store",
            "models",
            "services",
            "workflow_services",
            "apply_services",
            "cache",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, source)


class AIAgenticUnderstandingDecisionTests(SimpleTestCase):
    class FakeAnalysisProvider:
        def __init__(
            self,
            responses=None,
            exception=None,
            clarification_responses=None,
            clarification_exception=None,
        ):
            self.responses = list(responses or [])
            self.exception = exception
            self.clarification_responses = list(clarification_responses or [])
            self.clarification_exception = clarification_exception
            self.analysis_call_count = 0
            self.clarification_call_count = 0
            self.calls = []
            self.clarification_calls = []

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            self.calls.append(dict(kwargs))
            if self.exception is not None:
                raise self.exception
            if not self.responses:
                raise RuntimeError("No fake analysis response configured.")
            return self.responses.pop(0)

        def generate_clarification_questions(self, **kwargs):
            self.clarification_call_count += 1
            self.clarification_calls.append(dict(deepcopy(kwargs)))
            if self.clarification_exception is not None:
                raise self.clarification_exception
            if not self.clarification_responses:
                raise RuntimeError("No fake clarification response configured.")
            return self.clarification_responses.pop(0)

    def _state(self, description="Create a modern skincare store for young women.", **overrides):
        state: AIStoreAgentState = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": description,
            "normalized_description": description,
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 1,
        }
        state.update(overrides)
        return state

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    def _analysis_payload(
        self,
        *,
        language="en",
        sufficient=True,
        domains=None,
        business_summary="A clear proposed store.",
        target_audience="",
        product_direction=None,
        blocking=None,
        ambiguities=None,
    ) -> dict:
        if sufficient:
            domains = domains if domains is not None else ["beauty"]
            product_direction = (
                product_direction if product_direction is not None else ["skincare"]
            )
            blocking = blocking if blocking is not None else []
        else:
            domains = domains if domains is not None else []
            product_direction = product_direction if product_direction is not None else []
            blocking = blocking if blocking is not None else ["store_domain"]
        return {
            "description_language": language,
            "description_sufficient": sufficient,
            "detected_store_domains": domains,
            "business_summary": business_summary,
            "target_audience": target_audience,
            "product_direction": product_direction,
            "blocking_missing_information": blocking,
            "ambiguities": ambiguities if ambiguities is not None else [],
        }

    def _run_understand_with_provider(self, provider, state=None):
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ) as mock_factory:
            update = understand_node(state or self._state())
        return update, mock_factory

    def _understand_and_decide(self, provider, state=None):
        base_state = state or self._state()
        understood_update, mock_factory = self._run_understand_with_provider(
            provider,
            base_state,
        )
        understood = {**base_state, **understood_update}
        decision = decide_node(understood)
        return {**understood, **decision}, mock_factory

    def _clarification_payload(self, questions=None):
        return {
            "clarification_questions": questions or [
                {
                    "question_key": "store_domain",
                    "question_text": "What type of store should be created?",
                    "options": ["Fashion", "Beauty", "Electronics"],
                }
            ]
        }

    def _provider_for_payload(self, payload, clarification_payload=None):
        return self.FakeAnalysisProvider(
            [self._as_provider_response(payload)],
            clarification_responses=[
                self._as_provider_response(
                    clarification_payload or self._clarification_payload()
                )
            ],
        )

    def _assert_safe_understand_failure(self, result):
        self.assertEqual(result["current_step"], "understand")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertFalse(result["understanding_valid"])
        self.assertFalse(result["description_sufficient"])
        self.assertEqual(result["draft_payload"], {})
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotIn("Traceback", json.dumps(result))

    def _assert_valid_mcq_questions(self, questions):
        self.assertIsInstance(questions, list)
        self.assertTrue(questions)
        for question in questions:
            self.assertEqual(set(question), {"question_key", "question_text", "options"})
            self.assertIsInstance(question["question_key"], str)
            self.assertTrue(question["question_key"].strip())
            self.assertIsInstance(question["question_text"], str)
            self.assertTrue(question["question_text"].strip())
            self.assertIsInstance(question["options"], list)
            self.assertGreaterEqual(len(question["options"]), 2)
            self.assertLessEqual(len(question["options"]), 5)
            self.assertEqual(
                len({option.casefold() for option in question["options"]}),
                len(question["options"]),
            )

    def test_input_safety_fails_before_provider_creation(self):
        invalid_cases = (
            {"store_id": 0},
            {"store_id": True},
            {"tenant_id": 0},
            {"user_id": -1},
            {"normalized_description": None},
            {"normalized_description": ""},
            {"normalized_description": "   "},
            {"normalized_description": []},
            {"normalized_description": {}},
        )

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                state = self._state(**overrides)
                with patch(
                    "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client"
                ) as mock_factory:
                    result = understand_node(state)

                mock_factory.assert_not_called()
                self._assert_safe_understand_failure(result)
                self.assertEqual(result["clarification_round_count"], 0)
                self.assertEqual(result["repair_attempt_count"], 1)
                serialized = json.dumps(result)
                self.assertNotIn("Identity values", serialized)
                self.assertNotIn("normalized_description", serialized)

    def test_ai_is_used_for_clear_and_vague_descriptions(self):
        for payload in (
            self._analysis_payload(sufficient=True),
            self._analysis_payload(sufficient=False),
        ):
            with self.subTest(sufficient=payload["description_sufficient"]):
                provider = self._provider_for_payload(payload)
                result, mock_factory = self._understand_and_decide(provider)

                mock_factory.assert_called_once_with()
                self.assertEqual(provider.analysis_call_count, 1)
                self.assertEqual(provider.calls[0]["tenant_id"], 101)
                self.assertEqual(provider.calls[0]["store_id"], 10)
                self.assertEqual(
                    provider.calls[0]["normalized_description"],
                    "Create a modern skincare store for young women.",
                )
                self.assertIn(result["route_decision"], {"blueprint", "clarify"})

    def test_short_specific_description_can_route_to_blueprint_from_ai_output(self):
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=True,
                domains=["coffee"],
                business_summary="A small coffee shop concept.",
                product_direction=["coffee drinks"],
            )
        )

        result, _mock_factory = self._understand_and_decide(
            provider,
            self._state("Coffee shop"),
        )

        self.assertEqual(result["description_word_count"], 2)
        self.assertTrue(result["description_sufficient"])
        self.assertEqual(result["detected_store_domains"], ["coffee"])
        self.assertEqual(result["route_decision"], "blueprint")
        self.assertEqual(
            result["understanding_reasons"],
            ["ai_semantic_analysis_sufficient"],
        )

    def test_long_vague_description_can_route_to_clarify_from_ai_output(self):
        description = (
            "I want a beautiful modern online business with excellent quality "
            "and a great customer experience for everyone."
        )
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                blocking=["store_domain"],
                ambiguities=["The business domain is not specified."],
            )
        )

        result, _mock_factory = self._understand_and_decide(
            provider,
            self._state(description),
        )

        self.assertGreater(result["description_word_count"], 10)
        self.assertFalse(result["description_sufficient"])
        self.assertEqual(result["route_decision"], "clarify")
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(
            result["understanding_reasons"],
            ["ai_semantic_analysis_requires_clarification"],
        )

    def test_clear_english_and_arabic_analysis_route_to_blueprint(self):
        cases = (
            (
                "Create a beauty store for skincare products.",
                self._analysis_payload(
                    language="en",
                    sufficient=True,
                    domains=["beauty"],
                    product_direction=["skincare"],
                ),
            ),
            (
                "\u0623\u0631\u064a\u062f \u0645\u062a\u062c\u0631 \u0642\u0647\u0648\u0629 \u0645\u062e\u062a\u0635\u0629",
                self._analysis_payload(
                    language="ar",
                    sufficient=True,
                    domains=["coffee"],
                    business_summary="\u0645\u062a\u062c\u0631 \u0644\u0644\u0642\u0647\u0648\u0629 \u0627\u0644\u0645\u062e\u062a\u0635\u0629.",
                    product_direction=["specialty coffee"],
                ),
            ),
        )

        for description, payload in cases:
            with self.subTest(description=description):
                result, _mock_factory = self._understand_and_decide(
                    self._provider_for_payload(payload),
                    self._state(description),
                )

                self.assertEqual(result["description_language"], payload["description_language"])
                self.assertEqual(result["route_decision"], "blueprint")

    def test_ai_driven_clarification_path_builds_runner_safe_payload(self):
        questions = [
            {
                "question_key": "store_domain",
                "question_text": "What type of store should be created?",
                "options": ["Clothing", "Coffee", "Books"],
            }
        ]
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                blocking=["store_domain"],
            ),
            clarification_payload=self._clarification_payload(questions),
        )
        understood, _mock_factory = self._understand_and_decide(provider)

        with patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=provider,
        ):
            clarify_update = clarify_node(understood)
        final_state = {**understood, **clarify_update, **human_review_node({**understood, **clarify_update})}

        self.assertEqual(provider.clarification_call_count, 1)
        self.assertEqual(final_state["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(final_state["mode"], "clarification")
        self.assertEqual(final_state["validation_errors"], [])
        self.assertTrue(final_state["draft_payload"]["clarification_needed"])
        self.assertEqual(final_state["draft_payload"]["clarification_questions"], questions)
        self.assertEqual(final_state["clarification_questions"], questions)

    def test_multiple_domain_ambiguity_uses_ai_question_without_python_selection(self):
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                domains=["fashion", "electronics"],
                product_direction=[],
                blocking=["primary_store_domain"],
            )
        )

        result, _mock_factory = self._understand_and_decide(provider)

        self.assertEqual(result["detected_store_domains"], ["fashion", "electronics"])
        self.assertEqual(result["route_decision"], "clarify")
        self.assertEqual(result["blocking_missing_information"], ["primary_store_domain"])
        self.assertEqual(result["clarification_questions"], [])

    def test_exact_schema_rejects_missing_and_extra_keys(self):
        base = self._analysis_payload()
        payloads = []
        missing = dict(base)
        missing.pop("business_summary")
        payloads.append(missing)
        for extra_key in (
            "route_decision",
            "recommended_route",
            "reasoning",
            "chain_of_thought",
            "draft_payload",
            "status",
            "mode",
            "clarification_questions",
        ):
            invalid = dict(base)
            invalid[extra_key] = "invalid"
            payloads.append(invalid)

        for payload in payloads:
            with self.subTest(keys=sorted(payload.keys())):
                result, _mock_factory = self._run_understand_with_provider(
                    self._provider_for_payload(payload)
                )

                self._assert_safe_understand_failure(result)

    def test_field_validation_and_safe_normalization(self):
        duplicate_payload = self._analysis_payload(
            domains=["Beauty", " beauty ", "BEAUTY"],
            product_direction=["Skincare", " skincare "],
        )
        result, _mock_factory = self._understand_and_decide(
            self._provider_for_payload(duplicate_payload)
        )
        self.assertEqual(result["detected_store_domains"], ["Beauty"])
        self.assertEqual(result["product_direction"], ["Skincare"])
        self.assertEqual(result["route_decision"], "blueprint")

        invalid_cases = (
            {"description_language": "fr"},
            {"description_sufficient": "yes"},
            {"detected_store_domains": True},
            {"detected_store_domains": [123]},
            {"detected_store_domains": [" "]},
            {"business_summary": ""},
            {"target_audience": None},
            {"product_direction": "skincare"},
            {"product_direction": ["a", "b", "c", "d", "e", "f"]},
            {"blocking_missing_information": ["not valid"]},
            {"blocking_missing_information": ["a", "b", "c", "d", "e", "f"]},
            {"ambiguities": "unclear"},
        )
        for override in invalid_cases:
            payload = self._analysis_payload()
            payload.update(override)
            with self.subTest(override=override):
                result, _mock_factory = self._run_understand_with_provider(
                    self._provider_for_payload(payload)
                )
                self._assert_safe_understand_failure(result)

        non_serializable_payload = self._analysis_payload()
        non_serializable_payload["business_summary"] = object()
        non_serializable_provider = self.FakeAnalysisProvider(
            [{"choices": [{"message": {"content": non_serializable_payload}}]}]
        )
        result, _mock_factory = self._run_understand_with_provider(
            non_serializable_provider
        )
        self._assert_safe_understand_failure(result)

    def test_optional_defaults_cannot_be_blocking_information(self):
        optional_keys = (
            "currency",
            "timezone",
            "logo_url",
            "font_family",
            "primary_color",
            "exact_product_count",
        )

        for optional_key in optional_keys:
            provider = self._provider_for_payload(
                self._analysis_payload(
                    sufficient=False,
                    blocking=[optional_key],
                )
            )
            with self.subTest(optional_key=optional_key), patch(
                "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
                return_value=provider,
            ), patch(
                "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client"
            ) as mock_clarify_provider:
                result = compile_agentic_graph().invoke(self._state())

                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                self.assertEqual(result["route_decision"], "failed_recoverable")
                self.assertEqual(result.get("clarification_questions", []), [])
                mock_clarify_provider.assert_not_called()

    def test_cross_field_contradictions_fail_closed(self):
        cases = (
            self._analysis_payload(
                sufficient=True,
                blocking=["store_domain"],
            ),
            self._analysis_payload(sufficient=True, domains=[]),
            self._analysis_payload(sufficient=True, product_direction=[]),
            self._analysis_payload(sufficient=True, language="unknown"),
            self._analysis_payload(sufficient=False, blocking=[]),
            self._analysis_payload(
                language="unknown",
                sufficient=True,
                domains=["coffee"],
                product_direction=["coffee"],
            ),
        )

        for payload in cases:
            with self.subTest(payload=payload):
                result, _mock_factory = self._run_understand_with_provider(
                    self._provider_for_payload(payload)
                )
                self._assert_safe_understand_failure(result)

    def test_clarify_question_validation_failures(self):
        invalid_question_lists = (
            [],
            [
                {"question_key": "one", "question_text": "Q?", "options": ["A", "B"]},
                {"question_key": "two", "question_text": "Q?", "options": ["A", "B"]},
                {"question_key": "three", "question_text": "Q?", "options": ["A", "B"]},
                {"question_key": "four", "question_text": "Q?", "options": ["A", "B"]},
            ],
            [{"question_key": "domain", "question_text": "Q?", "options": ["A", "B"]}],
            [{"question_key": "", "question_text": "Q?", "options": ["A", "B"]}],
            [{"question_key": "StoreDomain", "question_text": "Q?", "options": ["A", "B"]}],
            [{"question_key": "store_domain", "question_text": "", "options": ["A", "B"]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A"]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A", "B", "C", "D", "E", "F"]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A", "a"]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A", " "]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A", 2]}],
            [{"question_key": "store_domain", "question_text": "Q?", "options": ["A", "B"], "extra": "x"}],
            [{"question_key": "store_domain", "question_text": "Q?"}],
        )

        for questions in invalid_question_lists:
            provider = self._provider_for_payload(
                self._analysis_payload(sufficient=False, blocking=["store_domain"]),
                clarification_payload={"clarification_questions": questions},
            )
            with self.subTest(questions=questions):
                understood, _mock_factory = self._understand_and_decide(provider)
                with patch(
                    "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
                    return_value=provider,
                ):
                    result = clarify_node(understood)
                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                self.assertEqual(result["clarification_questions"], [])

    def test_parse_retry_success_and_failure(self):
        valid_provider = self.FakeAnalysisProvider(
            [
                {"choices": [{"message": {"content": "not-json"}}]},
                self._as_provider_response(self._analysis_payload()),
            ]
        )
        result, mock_factory = self._understand_and_decide(valid_provider)

        mock_factory.assert_called_once_with()
        self.assertEqual(valid_provider.analysis_call_count, 2)
        self.assertEqual(result["route_decision"], "blueprint")
        self.assertEqual(result["clarification_round_count"], 0)
        self.assertEqual(result["repair_attempt_count"], 1)

        invalid_provider = self.FakeAnalysisProvider(
            [
                {"choices": [{"message": {"content": "not-json"}}]},
                {"choices": [{"message": {"content": "still-not-json"}}]},
            ]
        )
        failure, _mock_factory = self._run_understand_with_provider(invalid_provider)

        self.assertEqual(invalid_provider.analysis_call_count, 2)
        self._assert_safe_understand_failure(failure)
        self.assertNotIn("not-json", json.dumps(failure))

    def test_provider_failures_fail_safely_without_retrying_invocation_errors(self):
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            side_effect=RuntimeError("factory secret 10.0.0.1"),
        ) as mock_factory:
            result = understand_node(self._state())

        mock_factory.assert_called_once_with()
        self._assert_safe_understand_failure(result)
        self.assertNotIn("factory secret", json.dumps(result))
        self.assertNotIn("10.0.0.1", json.dumps(result))

        provider = self.FakeAnalysisProvider(exception=RuntimeError("provider secret"))
        result, _mock_factory = self._run_understand_with_provider(provider)
        self.assertEqual(provider.analysis_call_count, 1)
        self._assert_safe_understand_failure(result)
        self.assertNotIn("provider secret", json.dumps(result))

        bad_shape_provider = self.FakeAnalysisProvider([{"done": True}, {"done": True}])
        result, _mock_factory = self._run_understand_with_provider(bad_shape_provider)
        self.assertEqual(bad_shape_provider.analysis_call_count, 2)
        self._assert_safe_understand_failure(result)

    def test_decide_remains_deterministic_and_fails_closed_for_malformed_state(self):
        state = {
            **self._state(),
            **self._analysis_payload(),
            "understanding_valid": True,
            "description_word_count": 6,
            "understanding_reasons": ["ai_semantic_analysis_sufficient"],
        }

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client"
        ) as mock_factory, patch(
            "AI_Store_Creation_Service.agentic.understanding.analyze_store_description"
        ) as mock_adapter:
            result = decide_node(state)

        mock_factory.assert_not_called()
        mock_adapter.assert_not_called()
        self.assertEqual(result["route_decision"], "blueprint")

        malformed_states = (
            {"understanding_valid": True},
            {**state, "description_sufficient": "yes"},
            {**state, "description_word_count": "6"},
            {**state, "understanding_reasons": []},
        )
        for malformed_state in malformed_states:
            with self.subTest(malformed_state=malformed_state):
                failure = decide_node(malformed_state)
                self.assertEqual(failure["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                self.assertEqual(failure["route_decision"], "failed_recoverable")

        insufficient_state = {
            **self._state(),
            **self._analysis_payload(sufficient=False, blocking=["store_domain"]),
            "understanding_valid": True,
            "description_word_count": 6,
            "clarification_questions": [],
            "understanding_reasons": ["ai_semantic_analysis_requires_clarification"],
        }
        self.assertEqual(decide_node(insufficient_state)["route_decision"], "clarify")

    def test_clarify_node_terminal_contract_and_defensive_copies(self):
        questions = [
            {
                "question_key": "store_domain",
                "question_text": "What should the store sell?",
                "options": ["Fashion", "Coffee"],
            }
        ]
        provider = self._provider_for_payload(
            self._analysis_payload(sufficient=False, blocking=["store_domain"]),
            clarification_payload=self._clarification_payload(questions),
        )
        understood, _mock_factory = self._understand_and_decide(provider)
        state = {**understood, "clarification_round_count": 0, "repair_attempt_count": 1}
        before = deepcopy(state)

        with patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=provider,
        ):
            result = clarify_node(state)

        self.assertEqual(state, before)
        self.assertEqual(result["current_step"], "clarify")
        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["validation_errors"], [])
        self.assertTrue(result["draft_payload"]["clarification_needed"])
        self.assertEqual(result["clarification_questions"], questions)
        self.assertEqual(result["draft_payload"]["clarification_questions"], questions)
        self.assertIsNot(
            result["clarification_questions"],
            result["draft_payload"]["clarification_questions"],
        )
        self.assertNotIn("clarification_round_count", result)
        self.assertNotIn("repair_attempt_count", result)

        malformed = clarify_node(self._state(clarification_questions=[]))
        self.assertEqual(malformed["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(malformed["draft_payload"], {})

    def test_clarify_calls_ai_with_semantic_context(self):
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                domains=["fashion", "electronics"],
                product_direction=[],
                blocking=["primary_store_domain"],
                ambiguities=["The description mentions fashion and electronics."],
            ),
            clarification_payload=self._clarification_payload(
                [
                    {
                        "question_key": "primary_store_domain",
                        "question_text": "Which domain should be primary?",
                        "options": ["Fashion", "Electronics", "Combined Store"],
                    }
                ]
            ),
        )
        understood, _mock_factory = self._understand_and_decide(provider)

        with patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=provider,
        ) as clarify_factory:
            result = clarify_node(understood)

        clarify_factory.assert_called_once_with()
        self.assertEqual(provider.clarification_call_count, 1)
        call = provider.clarification_calls[0]
        self.assertEqual(call["normalized_description"], understood["normalized_description"])
        self.assertEqual(call["clarification_round_count"], 0)
        self.assertEqual(
            call["semantic_analysis"]["detected_store_domains"],
            ["fashion", "electronics"],
        )
        self.assertEqual(
            call["semantic_analysis"]["blocking_missing_information"],
            ["primary_store_domain"],
        )
        self.assertEqual(
            call["semantic_analysis"]["ambiguities"],
            ["The description mentions fashion and electronics."],
        )
        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)

    def test_clarify_rejects_known_or_optional_questions(self):
        cases = (
            (
                ["product_direction"],
                {
                    "question_key": "target_audience",
                    "question_text": "Who is the target audience?",
                    "options": ["Young women", "Men"],
                },
            ),
            (
                ["currency"],
                {
                    "question_key": "currency",
                    "question_text": "Which currency?",
                    "options": ["USD", "EUR"],
                },
            ),
        )

        for blocking, question in cases:
            with self.subTest(question=question):
                provider = self._provider_for_payload(
                    self._analysis_payload(
                        sufficient=False,
                        domains=["coffee"],
                        target_audience="young women",
                        product_direction=[],
                        blocking=blocking,
                    ),
                    clarification_payload=self._clarification_payload([question]),
                )
                understood, _mock_factory = self._understand_and_decide(provider)
                with patch(
                    "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
                    return_value=provider,
                ):
                    result = clarify_node(understood)

                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                self.assertEqual(result["clarification_questions"], [])

    def test_clarify_parse_retry_and_provider_failures_are_safe(self):
        valid_questions = self._clarification_payload(
            [
                {
                    "question_key": "store_domain",
                    "question_text": "What should the store sell?",
                    "options": ["Coffee", "Fashion"],
                }
            ]
        )
        retry_provider = self.FakeAnalysisProvider(
            [self._as_provider_response(self._analysis_payload(sufficient=False))],
            clarification_responses=[
                {"choices": [{"message": {"content": "not-json"}}]},
                self._as_provider_response(valid_questions),
            ],
        )
        understood, _mock_factory = self._understand_and_decide(retry_provider)
        with patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=retry_provider,
        ):
            retry_result = clarify_node(understood)

        self.assertEqual(retry_provider.clarification_call_count, 2)
        self.assertEqual(retry_result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertNotIn("clarification_round_count", retry_result)

        failure_provider = self.FakeAnalysisProvider(
            [self._as_provider_response(self._analysis_payload(sufficient=False))],
            clarification_exception=RuntimeError("secret provider at 10.0.0.1"),
        )
        understood, _mock_factory = self._understand_and_decide(failure_provider)
        with patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=failure_provider,
        ):
            failure_result = clarify_node(understood)

        self.assertEqual(failure_provider.clarification_call_count, 1)
        self.assertEqual(failure_result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        serialized = json.dumps(failure_result)
        self.assertNotIn("secret provider", serialized)
        self.assertNotIn("10.0.0.1", serialized)

    def test_same_description_routes_only_by_ai_analysis(self):
        description = "I want to build this store."
        sufficient_provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=True,
                domains=["coffee"],
                product_direction=["coffee drinks"],
            )
        )
        insufficient_provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                blocking=["store_domain"],
            )
        )

        blueprint_result, _mock_factory = self._understand_and_decide(
            sufficient_provider,
            self._state(description),
        )
        clarify_result, _mock_factory = self._understand_and_decide(
            insufficient_provider,
            self._state(description),
        )

        self.assertEqual(blueprint_result["route_decision"], "blueprint")
        self.assertEqual(clarify_result["route_decision"], "clarify")

    def test_understand_decide_and_clarify_do_not_increment_counters(self):
        provider = self._provider_for_payload(
            self._analysis_payload(
                sufficient=False,
                blocking=["store_domain"],
            )
        )
        state = self._state(clarification_round_count=0, repair_attempt_count=1)
        before = deepcopy(state)

        understand_update, _mock_factory = self._run_understand_with_provider(
            provider,
            state,
        )
        understood = {**state, **understand_update}
        decision = decide_node(understood)
        clarification = clarify_node({**understood, **decision})

        self.assertEqual(state, before)
        self.assertNotIn("clarification_round_count", understand_update)
        self.assertNotIn("repair_attempt_count", understand_update)
        self.assertNotIn("clarification_round_count", decision)
        self.assertNotIn("repair_attempt_count", decision)
        self.assertNotIn("clarification_round_count", clarification)
        self.assertNotIn("repair_attempt_count", clarification)

    def test_source_boundaries_for_phase_1i(self):
        decide_source = inspect.getsource(decide_node)
        clarify_source = inspect.getsource(clarify_node)
        understand_node_source = inspect.getsource(understand_node)
        understanding_source = inspect.getsource(understanding)
        clarifying_source = inspect.getsource(clarifying)

        for source in (decide_source, clarify_source):
            for forbidden_reference in (
                "get_ai_provider_client",
                "providers",
                "prompts",
                "requests",
                "Ollama",
                "model_name",
                "HTTP",
            ):
                with self.subTest(source="decision_or_clarify", forbidden_reference=forbidden_reference):
                    self.assertNotIn(forbidden_reference, source)

        self.assertNotIn("get_ai_provider_client", understand_node_source)
        self.assertIn("analyze_store_description", understand_node_source)

        for forbidden_reference in (
            "Store.objects",
            "ThemeTemplate.objects",
            "selectors",
            "draft_store",
            "Redis",
            "cache",
            "workflow_services",
            "services",
            "apply_services",
            "APIClient",
            "requests.",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, understanding_source)

        for forbidden_reference in (
            "Store.objects",
            "ThemeTemplate.objects",
            "selectors",
            "draft_store",
            "Redis",
            "cache",
            "workflow_services",
            "services",
            "apply_services",
            "APIClient",
            "requests.",
        ):
            with self.subTest(adapter="clarifying", forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, clarifying_source)


class AIAgenticGraphSkeletonTests(SimpleTestCase):
    class FakeProvider:
        def __init__(self, payload, analysis_payload=None, clarification_payload=None):
            self.payload = payload
            self.analysis_payload = analysis_payload or {
                "description_language": "en",
                "description_sufficient": True,
                "detected_store_domains": ["beauty"],
                "business_summary": "A clear beauty store.",
                "target_audience": "young women",
                "product_direction": ["skincare"],
                "blocking_missing_information": [],
                "ambiguities": [],
            }
            self.clarification_payload = clarification_payload or {
                "clarification_questions": [
                    {
                        "question_key": "store_domain",
                        "question_text": "What type of store should be created?",
                        "options": ["Fashion", "Coffee", "Books"],
                    }
                ]
            }
            self.analysis_call_count = 0
            self.clarification_call_count = 0
            self.generate_call_count = 0

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            return AIAgenticGraphSkeletonTests._as_provider_response(
                self.analysis_payload
            )

        def generate_store_draft(self, **kwargs):
            self.generate_call_count += 1
            return AIAgenticGraphSkeletonTests._as_provider_response(self.payload)

        def generate_agentic_store_draft(self, **kwargs):
            return self.generate_store_draft(**kwargs)

        def generate_clarification_questions(self, **kwargs):
            self.clarification_call_count += 1
            return AIAgenticGraphSkeletonTests._as_provider_response(
                self.clarification_payload
            )

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return {
            "store": {"name": "My Store", "description": "Desc"},
            "store_settings": {
                "currency": "USD",
                "language": "en",
                "timezone": "UTC",
            },
            "theme": {
                "theme_template": "Modern",
                "primary_color": "#112233",
                "secondary_color": "rgb(255, 255, 255)",
                "font_family": "Inter",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [{"name": "Clothes"}, {"name": "Shoes"}],
            "products": [
                {
                    "name": "T-Shirt",
                    "description": "Cotton shirt",
                    "price": 25.5,
                    "sku": "TS-001",
                    "category_name": "Clothes",
                    "stock_quantity": 5,
                    "image_url": "",
                },
                {
                    "name": "Sneakers",
                    "description": "Running shoes",
                    "price": 70,
                    "sku": "SN-001",
                    "category_name": "Shoes",
                    "stock_quantity": 3,
                    "image_url": "",
                },
            ],
            "clarification_needed": False,
            "clarification_questions": [],
        }

    def _base_state(
        self,
        description="Create a modern fashion store for women",
        **overrides,
    ) -> AIStoreAgentState:
        state: AIStoreAgentState = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": description,
            "normalized_description": description,
            "available_theme_templates": ["Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
        }
        state.update(overrides)
        return state

    @staticmethod
    def _clarification_analysis_payload() -> dict:
        return {
            "description_language": "en",
            "description_sufficient": False,
            "detected_store_domains": [],
            "business_summary": "The store idea is not specific enough.",
            "target_audience": "",
            "product_direction": [],
            "blocking_missing_information": ["store_domain"],
            "ambiguities": ["The business domain is missing."],
        }

    def _invoke_with_fake_provider(
        self,
        state,
        payload=None,
        analysis_payload=None,
        clarification_payload=None,
    ):
        fake_provider = self.FakeProvider(
            payload or self._valid_full_draft_payload(),
            analysis_payload=analysis_payload,
            clarification_payload=clarification_payload,
        )
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=fake_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=fake_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=fake_provider,
        ):
            result = compile_agentic_graph().invoke(state)
        return result, fake_provider

    def _compiled_graph_edges(self):
        graph = compile_agentic_graph().get_graph()
        return {
            (edge.source, edge.target, edge.conditional)
            for edge in graph.edges
        }

    def test_langgraph_is_importable_and_version_matches_requirement(self):
        import langgraph

        self.assertIsNotNone(langgraph)
        self.assertEqual(package_version("langgraph"), "1.2.9")

    def test_build_agentic_graph_returns_state_graph(self):
        self.assertIsInstance(build_agentic_graph(), StateGraph)

    def test_compile_agentic_graph_compiles_successfully(self):
        compiled_graph = compile_agentic_graph()

        self.assertTrue(hasattr(compiled_graph, "invoke"))
        self.assertTrue(hasattr(compiled_graph, "get_graph"))

    def test_compiled_graph_contains_all_expected_nodes(self):
        graph = compile_agentic_graph().get_graph()

        self.assertEqual(
            set(graph.nodes.keys()),
            {
                START,
                "understand",
                "merge_answers",
                "decide",
                "clarify",
                "blueprint",
                "generate",
                "validate",
                "repair",
                "human_review",
                "recoverable_failure",
                END,
            },
        )

    def test_graph_contains_required_deterministic_topology(self):
        self.assertEqual(
            self._compiled_graph_edges(),
            {
                (START, "understand", True),
                (START, "merge_answers", True),
                (START, "recoverable_failure", True),
                ("merge_answers", "understand", True),
                ("merge_answers", "recoverable_failure", True),
                ("understand", "decide", False),
                ("decide", "clarify", True),
                ("decide", "blueprint", True),
                ("decide", "recoverable_failure", True),
                ("clarify", "human_review", False),
                ("blueprint", "generate", False),
                ("generate", "validate", True),
                ("generate", "recoverable_failure", True),
                ("validate", "human_review", True),
                ("validate", "repair", True),
                ("validate", "recoverable_failure", True),
                ("repair", "validate", True),
                ("repair", "recoverable_failure", True),
                ("human_review", END, False),
                ("recoverable_failure", END, False),
            },
        )

    def test_compiled_graph_has_no_checkpointer(self):
        self.assertIsNone(getattr(compile_agentic_graph(), "checkpointer", None))

    def test_blueprint_path_reaches_ready_for_review_when_validation_errors_empty(self):
        result, fake_provider = self._invoke_with_fake_provider(
            self._base_state(
                "Create a modern skincare store for young women.",
                route_decision="clarify",
            )
        )

        self.assertEqual(fake_provider.generate_call_count, 1)
        self.assertEqual(fake_provider.clarification_call_count, 0)
        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["mode"], "draft_ready")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["draft_payload"]["clarification_needed"], False)
        self.assertEqual(result["repair_attempt_count"], 0)
        self.assertEqual(result["detected_store_domains"], ["beauty"])

    def test_clarification_path_reaches_needs_clarification(self):
        result, fake_provider = self._invoke_with_fake_provider(
            self._base_state(
                "I want to create a beautiful online store.",
                clarification_round_count=0,
            ),
            analysis_payload=self._clarification_analysis_payload(),
        )

        self.assertEqual(fake_provider.analysis_call_count, 1)
        self.assertEqual(fake_provider.clarification_call_count, 1)
        self.assertEqual(fake_provider.generate_call_count, 0)
        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(
            result["clarification_questions"][0]["question_key"],
            "store_domain",
        )
        self.assertEqual(result["clarification_round_count"], 0)

    def test_invalid_understanding_state_reaches_failed_recoverable(self):
        result = compile_agentic_graph().invoke(
            self._base_state(store_id=0)
        )

        self.assertEqual(result["current_step"], "recoverable_failure")
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)

    def test_valid_generated_payload_clears_stale_repairable_validation_errors(self):
        result, _fake_provider = self._invoke_with_fake_provider(
            self._base_state(
                "Create a modern skincare store for young women.",
                validation_errors=[
                    {
                        "path": "products.0.price",
                        "code": "invalid_price",
                        "message": "Product price must be positive.",
                        "repairable": True,
                    }
                ],
                clarification_round_count=0,
            )
        )

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["repair_attempt_count"], 0)
        self.assertEqual(result["clarification_round_count"], 0)

    def test_valid_generated_payload_ignores_stale_non_repairable_validation_errors(self):
        result, _fake_provider = self._invoke_with_fake_provider(
            self._base_state(
                "Create a modern skincare store for young women.",
                validation_errors=[
                    {
                        "path": "products.0.sku",
                        "code": "missing_sku",
                        "message": "Product SKU is required.",
                        "repairable": False,
                    }
                ],
            )
        )

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["repair_attempt_count"], 0)

    def test_valid_generated_payload_ignores_malformed_incoming_validation_errors(self):
        result, _fake_provider = self._invoke_with_fake_provider(
            self._base_state(
                "Create a modern skincare store for young women.",
                validation_errors="not-a-list",
            )
        )

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["validation_errors"], [])

    def test_graph_nodes_do_not_mutate_input_dictionaries(self):
        state = self._base_state(
            "Create a modern skincare store for young women.",
            available_theme_templates=[],
            route_decision="blueprint",
            validation_errors=[
                {
                    "path": "products.0.price",
                    "code": "invalid_price",
                    "message": "Product price must be positive.",
                    "repairable": True,
                }
            ],
            clarification_questions=[{"question_key": "audience"}],
            clarification_round_count=1,
            repair_attempt_count=1,
        )

        for node in (
            understand_node,
            decide_node,
            clarify_node,
            blueprint_node,
            generate_node,
            validate_node,
            repair_node,
            human_review_node,
            recoverable_failure_node,
        ):
            with self.subTest(node=node.__name__):
                candidate = deepcopy(state)
                before = deepcopy(candidate)
                if node is understand_node:
                    with patch(
                        "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
                        side_effect=RuntimeError("safe test failure"),
                    ):
                        update = node(candidate)
                else:
                    update = node(candidate)

                self.assertEqual(candidate, before)
                self.assertIsInstance(update, dict)

    def test_graph_nodes_do_not_reference_forbidden_persistence_systems(self):
        nodes_source = "\n".join(
            inspect.getsource(node)
            for node in (
                understand_node,
                decide_node,
                clarify_node,
                blueprint_node,
                generate_node,
                validate_node,
                repair_node,
                human_review_node,
                recoverable_failure_node,
            )
        )

        for forbidden_reference in (
            "get_ai_provider_client",
            "save_ai_draft",
            "get_ai_draft",
            "Store.objects",
            "apply_current_ai_draft",
            "workflow_services",
            "requests.",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, nodes_source)

    def test_no_graph_node_produces_applied_status(self):
        state = self._base_state(
            "Create a modern skincare store for young women.",
            available_theme_templates=[],
        )

        for node in (
            understand_node,
            decide_node,
            clarify_node,
            blueprint_node,
            generate_node,
            validate_node,
            repair_node,
            human_review_node,
            recoverable_failure_node,
        ):
            with self.subTest(node=node.__name__):
                self.assertNotEqual(node(state).get("status"), WORKFLOW_STATUS_APPLIED)

    def test_feature_flag_still_defaults_to_false(self):
        self.assertFalse(is_agentic_workflow_enabled())

    def test_legacy_production_workflow_is_not_connected_to_graph(self):
        services_source = inspect.getsource(services)
        workflow_source = inspect.getsource(workflow_services)

        self.assertNotIn("compile_agentic_graph", services_source)
        self.assertNotIn("compile_agentic_graph", workflow_source)
        self.assertNotIn("build_agentic_graph", services_source)
        self.assertNotIn("build_agentic_graph", workflow_source)
        self.assertNotIn("agentic.graph", services_source)
        self.assertNotIn("agentic.graph", workflow_source)


class AIAgenticGenerateIntegrationTests(SimpleTestCase):
    class FakeProvider:
        def __init__(self, responses=None, exception=None, analysis_payload=None):
            self.responses = list(responses or [])
            self.exception = exception
            self.analysis_payload = analysis_payload or {
                "description_language": "en",
                "description_sufficient": True,
                "detected_store_domains": ["beauty"],
                "business_summary": "A clear beauty store.",
                "target_audience": "young women",
                "product_direction": ["skincare"],
                "blocking_missing_information": [],
                "ambiguities": [],
            }
            self.analysis_call_count = 0
            self.generate_call_count = 0
            self.calls = []

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            if self.exception is not None:
                raise self.exception
            return AIAgenticGenerateIntegrationTests._as_provider_response(
                self.analysis_payload
            )

        def generate_store_draft(self, **kwargs):
            self.generate_call_count += 1
            self.calls.append(dict(kwargs))
            if self.exception is not None:
                raise self.exception
            if not self.responses:
                raise RuntimeError("No fake provider response configured.")
            return self.responses.pop(0)

        def generate_agentic_store_draft(self, **kwargs):
            return self.generate_store_draft(**kwargs)

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return AIAgenticGraphSkeletonTests._as_provider_response(payload)

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return AIAgenticGraphSkeletonTests._valid_full_draft_payload()

    @staticmethod
    def _clarification_payload() -> dict:
        return {
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

    def _base_state(self, **overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Raw user wording should not be used",
            "normalized_description": "Create a modern skincare store for young women.",
            "available_theme_templates": ["Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 1,
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _run_generate_with_provider(self, fake_provider, state=None):
        with patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=fake_provider,
        ) as mock_factory:
            result = generate_node(state or self._base_state())
        return result, mock_factory

    def _run_graph_with_provider(self, fake_provider, state=None):
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=fake_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=fake_provider,
        ):
            return compile_agentic_graph().invoke(state or self._base_state())

    def _assert_safe_generate_failure(self, result):
        self.assertEqual(result["current_step"], "generate")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["draft_payload"], {})
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotIn("Traceback", json.dumps(result))

    def test_generate_node_calls_provider_factory_lazily_and_once_on_success(self):
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._valid_full_draft_payload())]
        )

        result, mock_factory = self._run_generate_with_provider(fake_provider)

        mock_factory.assert_called_once_with()
        self.assertEqual(fake_provider.generate_call_count, 1)
        self.assertEqual(result["route_decision"], "validate")

    def test_provider_receives_normalized_description_and_theme_templates(self):
        original_templates = ["  Modern  ", "Classic", "Modern", "  Classic  "]
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._valid_full_draft_payload())]
        )

        result, _mock_factory = self._run_generate_with_provider(
            fake_provider,
            self._base_state(
                normalized_description="Normalized description",
                user_store_description="Unnormalized user wording",
                available_theme_templates=original_templates,
            ),
        )

        self.assertEqual(result["route_decision"], "validate")
        self.assertEqual(original_templates, ["  Modern  ", "Classic", "Modern", "  Classic  "])
        self.assertEqual(fake_provider.calls[0]["tenant_id"], 101)
        self.assertEqual(fake_provider.calls[0]["store_id"], 10)
        self.assertEqual(
            fake_provider.calls[0]["user_store_description"],
            "Normalized description",
        )
        self.assertEqual(
            fake_provider.calls[0]["available_theme_templates"],
            ["Modern", "Classic"],
        )

    def test_valid_provider_response_is_parsed_without_raw_response_storage(self):
        payload = self._valid_full_draft_payload()
        fake_provider = self.FakeProvider([self._as_provider_response(payload)])

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(result["mode"], "draft_ready")
        self.assertEqual(result["route_decision"], "validate")
        self.assertEqual(result["clarification_questions"], [])
        self.assertNotIn("choices", result)
        self.assertNotIn("message", result)

    def test_generate_provider_clarification_payload_fails_safely(self):
        payload = self._clarification_payload()
        fake_provider = self.FakeProvider([self._as_provider_response(payload)])

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self._assert_safe_generate_failure(result)
        self.assertNotEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)

    def test_generate_clarification_payload_missing_structural_keys_fails_safely(self):
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._clarification_payload())]
        )

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self._assert_safe_generate_failure(result)

    def test_targeted_normalization_repairs_common_provider_output(self):
        payload = self._valid_full_draft_payload()
        payload["products"][0].pop("image_url")
        payload["products"].extend(
            [
                {
                    "name": "Hat",
                    "description": "Sun hat",
                    "price": 12,
                    "sku": "HT-001",
                    "category_name": "Clothes",
                    "stock_quantity": 4,
                },
                {
                    "name": "Socks",
                    "description": "Cotton socks",
                    "price": 8,
                    "sku": "SO-001",
                    "category_name": "Clothes",
                    "stock_quantity": 6,
                },
                {
                    "name": "Bag",
                    "description": "Simple bag",
                    "price": 30,
                    "sku": "BG-001",
                    "category_name": "Clothes",
                    "stock_quantity": 2,
                },
            ]
        )
        fake_provider = self.FakeProvider([self._as_provider_response(payload)])

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self.assertEqual(result["draft_payload"]["products"][0]["image_url"], "")
        self.assertEqual(len(result["draft_payload"]["products"]), 4)

    def test_generate_does_not_clean_or_return_clarification_options(self):
        payload = self._clarification_payload()
        payload["clarification_questions"][0]["options"] = [
            " Fashion ",
            "",
            None,
            "  ",
            "Electronics",
        ]
        fake_provider = self.FakeProvider([self._as_provider_response(payload)])

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self._assert_safe_generate_failure(result)

    def test_parse_failure_on_first_response_retries_once_and_uses_second_payload(self):
        fake_provider = self.FakeProvider(
            [
                {"choices": [{"message": {"content": "not-json"}}]},
                self._as_provider_response(self._valid_full_draft_payload()),
            ]
        )

        result, mock_factory = self._run_generate_with_provider(fake_provider)

        mock_factory.assert_called_once_with()
        self.assertEqual(fake_provider.generate_call_count, 2)
        self.assertEqual(result["mode"], "draft_ready")

    def test_parse_failure_on_both_attempts_returns_safe_failure(self):
        fake_provider = self.FakeProvider(
            [
                {"choices": [{"message": {"content": "not-json"}}]},
                {"choices": [{"message": {"content": "still-not-json"}}]},
            ]
        )

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self.assertEqual(fake_provider.generate_call_count, 2)
        self._assert_safe_generate_failure(result)

    def test_provider_invocation_failure_does_not_retry(self):
        fake_provider = self.FakeProvider(exception=RuntimeError("provider secret"))

        result, _mock_factory = self._run_generate_with_provider(fake_provider)

        self.assertEqual(fake_provider.generate_call_count, 1)
        self._assert_safe_generate_failure(result)
        self.assertNotIn("provider secret", json.dumps(result))

    def test_agentic_generation_does_not_fall_back_to_legacy_generate_method(self):
        class LegacyOnlyProvider:
            def __init__(self):
                self.generate_store_draft_call_count = 0

            def generate_store_draft(self, **kwargs):
                self.generate_store_draft_call_count += 1
                return AIAgenticGenerateIntegrationTests._as_provider_response(
                    AIAgenticGenerateIntegrationTests._valid_full_draft_payload()
                )

        fake_provider = LegacyOnlyProvider()

        result, mock_factory = self._run_generate_with_provider(fake_provider)

        mock_factory.assert_called_once_with()
        self.assertEqual(fake_provider.generate_store_draft_call_count, 0)
        self._assert_safe_generate_failure(result)

    def test_provider_factory_failure_returns_safe_failure(self):
        with patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            side_effect=RuntimeError("factory secret"),
        ) as mock_factory:
            result = generate_node(self._base_state())

        mock_factory.assert_called_once_with()
        self._assert_safe_generate_failure(result)
        self.assertNotIn("factory secret", json.dumps(result))

    def test_malformed_identity_or_description_prevents_provider_creation(self):
        invalid_cases = (
            {"store_id": 0},
            {"tenant_id": 0},
            {"user_id": 0},
            {"normalized_description": ""},
            {"normalized_description": "   "},
            {"normalized_description": None},
        )

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                with patch(
                    "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client"
                ) as mock_factory:
                    result = generate_node(self._base_state(**overrides))

                mock_factory.assert_not_called()
                self._assert_safe_generate_failure(result)

    def test_missing_empty_or_malformed_theme_templates_prevents_provider_creation(self):
        invalid_cases = (
            {},
            {"available_theme_templates": []},
            {"available_theme_templates": ["   "]},
            {"available_theme_templates": ["Modern", 123]},
            {"available_theme_templates": "Modern"},
        )

        for overrides in invalid_cases:
            with self.subTest(overrides=overrides):
                state = self._base_state(**overrides)
                if overrides == {}:
                    state.pop("available_theme_templates")
                with patch(
                    "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client"
                ) as mock_factory:
                    result = generate_node(state)

                mock_factory.assert_not_called()
                self._assert_safe_generate_failure(result)

    def test_generate_node_does_not_mutate_input_or_counters_and_preserves_validation_errors(self):
        state = self._base_state(
            clarification_round_count=2,
            validation_errors=[
                {
                    "path": "products.0.price",
                    "code": "invalid_price",
                    "message": "Product price must be positive.",
                    "repairable": True,
                }
            ]
        )
        before = deepcopy(state)
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._valid_full_draft_payload())]
        )

        update, _mock_factory = self._run_generate_with_provider(fake_provider, state)

        self.assertEqual(state, before)
        combined = {**state, **update}
        self.assertEqual(combined["clarification_round_count"], 2)
        self.assertEqual(combined["repair_attempt_count"], 1)
        self.assertEqual(update["validation_errors"], before["validation_errors"])
        update["validation_errors"][0]["message"] = "Mutated"
        self.assertEqual(
            state["validation_errors"][0]["message"],
            "Product price must be positive.",
        )

    def test_route_after_generate_supports_validate_and_fails_closed(self):
        self.assertEqual(route_after_generate({"route_decision": "validate"}), "validate")
        for route_decision in ("repair", "human_review", "failed_recoverable", None):
            with self.subTest(route_decision=route_decision):
                self.assertEqual(
                    route_after_generate({"route_decision": route_decision}),
                    "failed_recoverable",
                )
        self.assertEqual(route_after_generate({}), "failed_recoverable")

    def test_graph_topology_contains_conditional_generate_routing(self):
        edges = {
            (edge.source, edge.target, edge.conditional)
            for edge in compile_agentic_graph().get_graph().edges
        }

        self.assertIn(("generate", "validate", True), edges)
        self.assertIn(("generate", "recoverable_failure", True), edges)
        self.assertNotIn(("generate", "validate", False), edges)

    def test_mocked_full_generation_graph_path_reaches_ready_for_review(self):
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._valid_full_draft_payload())]
        )

        result = self._run_graph_with_provider(fake_provider)

        self.assertEqual(fake_provider.generate_call_count, 1)
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["draft_payload"]["clarification_needed"], False)

    def test_mocked_generate_clarification_result_reaches_recoverable_failure(self):
        payload = self._clarification_payload()
        fake_provider = self.FakeProvider([self._as_provider_response(payload)])

        result = self._run_graph_with_provider(fake_provider)

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["clarification_questions"], [])

    def test_mocked_provider_failure_reaches_recoverable_failure(self):
        fake_provider = self.FakeProvider(exception=RuntimeError("provider secret"))

        result = self._run_graph_with_provider(fake_provider)

        self.assertEqual(result["current_step"], "recoverable_failure")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertNotIn("provider secret", json.dumps(result))

    def test_runner_rejects_human_review_without_draft_payload(self):
        fake_graph = AIAgenticRunnerTests.FakeCompiledGraph(
            {
                "store_id": 10,
                "tenant_id": 101,
                "user_id": 7,
                "user_store_description": "Create a coffee store for customers",
                "normalized_description": "Create a coffee store for customers",
                "clarification_round_count": 0,
                "repair_attempt_count": 0,
                "current_step": "human_review",
                "mode": "draft_ready",
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "route_decision": "human_review",
                "clarification_questions": [],
            }
        )

        with patch(
            "AI_Store_Creation_Service.agentic.runner.compile_agentic_graph",
            return_value=fake_graph,
        ):
            result = run_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                user_store_description="Create a coffee store for customers",
                normalized_description="Create a coffee store for customers",
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

    def test_generate_integration_does_not_reference_forbidden_systems(self):
        source = "\n".join(
            [
                inspect.getsource(generation),
                inspect.getsource(generate_node),
            ]
        )
        for forbidden_reference in (
            "Store.objects",
            "ThemeTemplate.objects",
            "selectors",
            "draft_store",
            "save_ai_draft",
            "save_ai_draft_meta",
            "workflow_services",
            "services",
            "apply_services",
            "Redis",
            "cache",
            "urlopen",
            "_post_json_request",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, source)

    def test_services_and_workflow_services_remain_unconnected_to_agentic_runner_or_graph(self):
        services_source = inspect.getsource(services)
        workflow_source = inspect.getsource(workflow_services)

        self.assertNotIn("agentic.runner", services_source)
        self.assertNotIn("agentic.runner", workflow_source)
        self.assertNotIn("run_agentic_workflow", services_source)
        self.assertNotIn("run_agentic_workflow", workflow_source)
        self.assertNotIn("route_after_generate", services_source)
        self.assertNotIn("route_after_generate", workflow_source)

    def test_feature_flag_still_defaults_to_false_and_no_generate_path_produces_applied(self):
        self.assertFalse(is_agentic_workflow_enabled())
        fake_provider = self.FakeProvider(
            [self._as_provider_response(self._valid_full_draft_payload())]
        )

        result = self._run_graph_with_provider(fake_provider)
        failure = generate_node(self._base_state(store_id=0))

        self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)
        self.assertNotEqual(failure.get("status"), WORKFLOW_STATUS_APPLIED)


class AIAgenticValidateIntegrationTests(SimpleTestCase):
    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return AIAgenticGraphSkeletonTests._valid_full_draft_payload()

    @staticmethod
    def _clarification_payload() -> dict:
        return {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return AIAgenticGraphSkeletonTests._as_provider_response(payload)

    class FakeProvider:
        def __init__(self, payload, analysis_payload=None, clarification_payload=None):
            self.payload = payload
            self.analysis_payload = analysis_payload or {
                "description_language": "en",
                "description_sufficient": True,
                "detected_store_domains": ["beauty"],
                "business_summary": "A clear beauty store.",
                "target_audience": "women",
                "product_direction": ["skincare"],
                "blocking_missing_information": [],
                "ambiguities": [],
            }
            self.clarification_payload = clarification_payload or {
                "clarification_questions": [
                    {
                        "question_key": "store_type",
                        "question_text": "What type of store?",
                        "options": ["Fashion", "Electronics"],
                    }
                ]
            }
            self.analysis_call_count = 0
            self.generate_call_count = 0
            self.clarification_call_count = 0
            self.regenerate_call_count = 0
            self.regenerate_section_call_count = 0

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            return AIAgenticValidateIntegrationTests._as_provider_response(
                self.analysis_payload
            )

        def generate_store_draft(self, **kwargs):
            self.generate_call_count += 1
            return AIAgenticValidateIntegrationTests._as_provider_response(self.payload)

        def generate_agentic_store_draft(self, **kwargs):
            return self.generate_store_draft(**kwargs)

        def generate_clarification_questions(self, **kwargs):
            self.clarification_call_count += 1
            return AIAgenticValidateIntegrationTests._as_provider_response(
                self.clarification_payload
            )

        def regenerate_store_draft(self, **kwargs):
            self.regenerate_call_count += 1
            return AIAgenticValidateIntegrationTests._as_provider_response(self.payload)

        def regenerate_store_draft_section(self, **kwargs):
            self.regenerate_section_call_count += 1
            target_section = kwargs["target_section"]
            return AIAgenticValidateIntegrationTests._as_provider_response(
                {target_section: self.payload[target_section]}
            )

    def _state(self, payload=None, mode="draft_ready", **overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a modern skincare store for women.",
            "normalized_description": "Create a modern skincare store for women.",
            "available_theme_templates": ["Modern"],
            "draft_payload": payload if payload is not None else self._valid_full_draft_payload(),
            "mode": mode,
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "validation_errors": [
                {
                    "path": "stale",
                    "code": "stale",
                    "message": "Stale error.",
                    "repairable": True,
                }
            ],
        }
        state.update(overrides)
        return state

    def _validate(self, payload=None, mode="draft_ready", **overrides):
        return validate_node(self._state(payload=payload, mode=mode, **overrides))

    def _issue_codes(self, issues):
        return [issue["code"] for issue in issues]

    def _assert_issue(self, issue, *, path, code, repairable):
        self.assertEqual(set(issue.keys()), {"path", "code", "message", "repairable"})
        self.assertEqual(issue["path"], path)
        self.assertEqual(issue["code"], code)
        self.assertIs(issue["repairable"], repairable)
        self.assertIsInstance(issue["message"], str)
        self.assertTrue(issue["message"].strip())
        json.dumps(issue)

    def _assert_failed_validation_result(self, result):
        self.assertEqual(result["current_step"], "validate")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertEqual(result["clarification_questions"], [])

    def test_valid_draft_ready_payload_produces_no_issues_and_routes_to_human_review(self):
        payload, mode, issues = validation.validate_generated_draft(
            draft_payload=self._valid_full_draft_payload(),
            expected_mode="draft_ready",
            available_theme_templates=["Modern"],
        )
        result = self._validate()

        self.assertEqual(mode, "draft_ready")
        self.assertEqual(issues, [])
        self.assertEqual(payload["clarification_needed"], False)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["mode"], "draft_ready")
        json.dumps(result)

    def test_valid_clarification_payload_skips_empty_structural_sections_and_routes_to_human_review(self):
        payload = self._clarification_payload()
        result = self._validate(payload, mode="clarification")

        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["draft_payload"]["store"], {})
        self.assertEqual(result["draft_payload"]["categories"], [])
        self.assertEqual(
            result["clarification_questions"],
            payload["clarification_questions"],
        )

    def test_missing_or_non_mapping_or_non_serializable_payload_fails_closed(self):
        cases = ("missing", [], {"store": object()})
        expected_codes = (
            "draft_payload_invalid",
            "draft_payload_invalid",
            "draft_payload_not_serializable",
        )
        for payload, expected_code in zip(cases, expected_codes):
            with self.subTest(payload_type=type(payload).__name__):
                state = self._state()
                if payload == "missing":
                    state.pop("draft_payload")
                else:
                    state["draft_payload"] = payload
                result = validate_node(state)

                self._assert_failed_validation_result(result)
                self.assertEqual(result["validation_errors"][0]["code"], expected_code)

    def test_contradictory_response_flags_create_repairable_response_mode_issue(self):
        payload = self._valid_full_draft_payload()
        payload["clarification_needed"] = False
        payload["clarification_questions"] = self._clarification_payload()[
            "clarification_questions"
        ]

        result = self._validate(payload)

        self.assertEqual(result["route_decision"], "repair")
        self.assertNotIn("mode", result)
        self.assertNotIn(
            "clarification_questions_invalid",
            self._issue_codes(result["validation_errors"]),
        )
        self._assert_issue(
            result["validation_errors"][0],
            path="clarification_questions",
            code="response_mode_invalid",
            repairable=True,
        )

    def test_repair_path_does_not_clear_existing_mode_when_detected_mode_is_missing(self):
        payload = self._valid_full_draft_payload()
        payload["clarification_needed"] = False
        payload["clarification_questions"] = self._clarification_payload()[
            "clarification_questions"
        ]
        state = self._state(payload=payload, mode="draft_ready", repair_attempt_count=0)

        result = validate_node(state)
        merged_state = {**state, **result}

        self.assertEqual(result["route_decision"], "repair")
        self.assertNotIn("mode", result)
        self.assertEqual(merged_state["mode"], "draft_ready")
        self.assertIn("response_mode_invalid", self._issue_codes(result["validation_errors"]))
        self.assertTrue(all(issue["repairable"] for issue in result["validation_errors"]))
        self.assertNotIn("repair_attempt_count", result)
        self.assertEqual(state["repair_attempt_count"], 0)

    def test_second_validate_after_repair_does_not_create_mode_mismatch_from_lost_mode(self):
        payload = self._valid_full_draft_payload()
        payload["clarification_needed"] = False
        payload["clarification_questions"] = self._clarification_payload()[
            "clarification_questions"
        ]
        state = self._state(payload=payload, mode="draft_ready", repair_attempt_count=0)

        first_update = validate_node(state)
        next_state = {**state, **first_update, "repair_attempt_count": 1}
        second_update = validate_node(next_state)
        second_codes = self._issue_codes(second_update["validation_errors"])

        self.assertEqual(next_state["mode"], "draft_ready")
        self.assertEqual(second_update["route_decision"], "repair")
        self.assertNotIn("mode", second_update)
        self.assertIn("response_mode_invalid", second_codes)
        self.assertNotIn("state_mode_mismatch", second_codes)
        self.assertNotIn("repair_attempt_count", second_update)

    def test_invalid_clarification_mcq_uses_stable_clarification_issue_code(self):
        cases = (
            ("too_few_options", {"options": ["Fashion"]}),
            ("empty_question_key", {"question_key": "   "}),
        )

        for name, question_update in cases:
            with self.subTest(name=name):
                payload = self._clarification_payload()
                payload["clarification_questions"][0].update(question_update)

                normalized_payload, detected_mode, issues = validation.validate_generated_draft(
                    draft_payload=payload,
                    expected_mode="clarification",
                    available_theme_templates=["Modern"],
                )
                result = self._validate(payload, mode="clarification")
                codes = self._issue_codes(issues)

                self.assertEqual(normalized_payload["clarification_needed"], True)
                self.assertIsNone(detected_mode)
                self.assertEqual(codes, ["clarification_questions_invalid"])
                self.assertNotIn("response_mode_invalid", codes)
                self.assertNotIn("state_mode_mismatch", codes)
                self._assert_issue(
                    issues[0],
                    path="clarification_questions",
                    code="clarification_questions_invalid",
                    repairable=True,
                )
                self.assertEqual(result["route_decision"], "repair")
                self.assertNotIn("mode", result)

    def test_circular_payload_returns_safe_not_serializable_issue(self):
        payload = {}
        payload["self"] = payload

        normalized_payload, detected_mode, issues = validation.validate_generated_draft(
            draft_payload=payload,
            expected_mode="draft_ready",
            available_theme_templates=["Modern"],
        )
        serialized = json.dumps({"payload": normalized_payload, "issues": issues})

        self.assertEqual(normalized_payload, {})
        self.assertIsNone(detected_mode)
        self.assertEqual(len(issues), 1)
        self._assert_issue(
            issues[0],
            path="draft_payload",
            code="draft_payload_not_serializable",
            repairable=False,
        )
        self.assertEqual(
            issues[0]["message"],
            "Draft payload must contain only JSON-serializable values.",
        )
        self.assertNotIn("Circular reference detected", serialized)

    def test_validate_node_boundary_converts_unexpected_adapter_exception_to_safe_failure(self):
        with patch(
            "AI_Store_Creation_Service.agentic.nodes.validate.validate_generated_draft",
            side_effect=RuntimeError("secret provider database redis detail at 10.0.0.1"),
        ):
            result = validate_node(self._state())

        self._assert_failed_validation_result(result)
        self.assertEqual(result["draft_payload"], {})
        self.assertEqual(len(result["validation_errors"]), 1)
        self._assert_issue(
            result["validation_errors"][0],
            path="draft_payload",
            code="validation_internal_failure",
            repairable=False,
        )
        serialized = json.dumps(result)
        self.assertNotIn("secret provider database redis detail at 10.0.0.1", serialized)

    def test_state_mode_mismatch_is_non_repairable(self):
        result = self._validate(self._valid_full_draft_payload(), mode="clarification")

        self._assert_failed_validation_result(result)
        self._assert_issue(
            result["validation_errors"][0],
            path="draft_payload",
            code="state_mode_mismatch",
            repairable=False,
        )

    def test_invalid_store_settings_theme_categories_and_products_create_structured_issues(self):
        payload = self._valid_full_draft_payload()
        payload["store"] = {"description": "Missing name"}
        payload["store_settings"]["currency"] = ""
        payload["theme"]["primary_color"] = "not-a-color"
        payload["categories"] = [{"name": "Clothes"}, {"name": "Clothes"}]
        payload["products"][0]["price"] = -1

        result = self._validate(payload)

        self.assertEqual(result["route_decision"], "repair")
        self.assertEqual(
            self._issue_codes(result["validation_errors"]),
            [
                "store_section_invalid",
                "store_settings_section_invalid",
                "theme_section_invalid",
                "categories_section_invalid",
                "products_section_invalid",
            ],
        )
        self._assert_issue(
            result["validation_errors"][0],
            path="store",
            code="store_section_invalid",
            repairable=True,
        )

    def test_theme_template_context_and_availability_issues_are_classified(self):
        payload = self._valid_full_draft_payload()

        missing_context = self._validate(payload, available_theme_templates=[])
        malformed_context = self._validate(payload, available_theme_templates=["Modern", 123])
        unavailable = self._validate(
            payload,
            available_theme_templates=["Classic"],
        )

        self._assert_failed_validation_result(missing_context)
        self._assert_issue(
            missing_context["validation_errors"][0],
            path="available_theme_templates",
            code="theme_templates_context_invalid",
            repairable=False,
        )
        self._assert_failed_validation_result(malformed_context)
        self.assertEqual(
            malformed_context["validation_errors"][0]["code"],
            "theme_templates_context_invalid",
        )
        self.assertEqual(unavailable["route_decision"], "repair")
        self._assert_issue(
            unavailable["validation_errors"][0],
            path="theme.theme_template",
            code="theme_template_unavailable",
            repairable=True,
        )

    def test_theme_template_names_are_normalized_without_mutating_input(self):
        templates = ["  Modern  ", "Classic", "Modern"]
        payload = self._valid_full_draft_payload()

        result = self._validate(payload, available_theme_templates=templates)

        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(templates, ["  Modern  ", "Classic", "Modern"])

    def test_product_validation_detects_stock_duplicate_sku_and_category_mismatch(self):
        cases = (
            ("stock_quantity", -1),
            ("sku", "SN-001"),
            ("category_name", "Missing"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                payload = self._valid_full_draft_payload()
                payload["products"][0][field] = value

                result = self._validate(payload)

                self.assertEqual(result["route_decision"], "repair")
                self.assertIn("products_section_invalid", self._issue_codes(result["validation_errors"]))

    def test_validate_node_does_not_mutate_input_and_ignores_stale_errors(self):
        state = self._state(validation_errors="malformed stale value")
        before = deepcopy(state)

        result = validate_node(state)

        self.assertEqual(state, before)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["validation_errors"], [])

    def test_invalid_payload_recomputes_errors_even_when_incoming_errors_are_empty(self):
        payload = self._valid_full_draft_payload()
        payload["products"][0]["price"] = 0

        result = self._validate(payload, validation_errors=[])

        self.assertEqual(result["route_decision"], "repair")
        self.assertEqual(result["validation_errors"][0]["code"], "products_section_invalid")

    def test_repair_routing_respects_repair_counter_boundaries(self):
        payload = self._valid_full_draft_payload()
        payload["products"][0]["price"] = 0

        repairable = self._validate(payload, repair_attempt_count=MAX_REPAIR_ATTEMPTS - 1)
        at_limit = self._validate(payload, repair_attempt_count=MAX_REPAIR_ATTEMPTS)
        above_limit = self._validate(payload, repair_attempt_count=MAX_REPAIR_ATTEMPTS + 1)
        bool_count = self._validate(payload, repair_attempt_count=True)
        negative_count = self._validate(payload, repair_attempt_count=-1)

        self.assertEqual(repairable["route_decision"], "repair")
        self.assertNotIn("repair_attempt_count", repairable)
        for result in (at_limit, above_limit, bool_count, negative_count):
            self._assert_failed_validation_result(result)

    def test_counters_remain_independent(self):
        payload = self._valid_full_draft_payload()
        payload["products"][0]["price"] = 0
        state = self._state(
            payload=payload,
            clarification_round_count=2,
            repair_attempt_count=1,
        )

        result = validate_node(state)

        self.assertEqual(result["route_decision"], "repair")
        self.assertNotIn("clarification_round_count", result)
        self.assertNotIn("repair_attempt_count", result)

    def test_unexpected_validator_exception_is_safe_non_repairable_failure(self):
        with patch(
            "AI_Store_Creation_Service.agentic.validation.validate_store_section",
            side_effect=RuntimeError("secret database or provider detail"),
        ):
            result = self._validate()

        self._assert_failed_validation_result(result)
        self.assertIn("validation_internal_failure", self._issue_codes(result["validation_errors"]))
        serialized = json.dumps(result)
        self.assertNotIn("secret database or provider detail", serialized)

    def test_valid_graph_paths_include_empty_validation_errors(self):
        full_provider = self.FakeProvider(self._valid_full_draft_payload())
        clarification_provider = self.FakeProvider(
            self._valid_full_draft_payload(),
            analysis_payload={
                "description_language": "en",
                "description_sufficient": False,
                "detected_store_domains": [],
                "business_summary": "The store idea needs clarification.",
                "target_audience": "",
                "product_direction": [],
                "blocking_missing_information": ["store_type"],
                "ambiguities": ["The store type is missing."],
            },
            clarification_payload={
                "clarification_questions": self._clarification_payload()[
                    "clarification_questions"
                ]
            },
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=full_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=full_provider,
        ):
            ready = compile_agentic_graph().invoke(self._state())
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=clarification_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=clarification_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=clarification_provider,
        ):
            needs = compile_agentic_graph().invoke(self._state())

        self.assertEqual(ready["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(ready["validation_errors"], [])
        self.assertEqual(needs["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(needs["validation_errors"], [])
        self.assertEqual(needs["clarification_questions"], needs["draft_payload"]["clarification_questions"])

    def test_invalid_graph_path_enters_repair_then_fails_at_limit(self):
        payload = self._valid_full_draft_payload()
        payload["products"][0]["price"] = 0
        provider = self.FakeProvider(payload)

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        codes = self._issue_codes(result["validation_errors"])
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["repair_attempt_count"], MAX_REPAIR_ATTEMPTS)
        self.assertLessEqual(result["repair_attempt_count"], MAX_REPAIR_ATTEMPTS)
        self.assertEqual(provider.regenerate_section_call_count, MAX_REPAIR_ATTEMPTS)
        self.assertIn("products_section_invalid", codes)
        self.assertNotIn("state_mode_mismatch", codes)

    def test_runner_rejects_successful_terminal_states_with_validation_errors_missing_or_malformed(self):
        cases = (
            {"validation_errors": [{"path": "x", "code": "x", "message": "x", "repairable": True}]},
            {"validation_errors": "malformed"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                fake_graph = AIAgenticRunnerTests.FakeCompiledGraph(
                    AIAgenticRunnerTests()._ready_terminal_state(**overrides)
                )
                result, _mock_compile = AIAgenticRunnerTests()._run_with_fake_graph(fake_graph)
                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

        missing = AIAgenticRunnerTests()._ready_terminal_state()
        missing.pop("validation_errors")
        fake_graph = AIAgenticRunnerTests.FakeCompiledGraph(missing)
        result, _mock_compile = AIAgenticRunnerTests()._run_with_fake_graph(fake_graph)
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

        clarification = AIAgenticRunnerTests()._clarification_terminal_state(
            validation_errors=[
                {
                    "path": "x",
                    "code": "x",
                    "message": "x",
                    "repairable": True,
                }
            ]
        )
        fake_graph = AIAgenticRunnerTests.FakeCompiledGraph(clarification)
        result, _mock_compile = AIAgenticRunnerTests()._run_with_fake_graph(fake_graph)
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

    def test_validate_integration_does_not_reference_forbidden_systems(self):
        source = "\n".join(
            [
                inspect.getsource(validation),
                inspect.getsource(validate_node),
            ]
        )
        for forbidden_reference in (
            "get_ai_provider_client",
            "providers",
            "Store.objects",
            "ThemeTemplate.objects",
            "selectors",
            "draft_store",
            "save_ai_draft",
            "save_ai_draft_meta",
            "workflow_services",
            "services",
            "apply_services",
            "Redis",
            "cache",
            "requests",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, source)

    def test_feature_flag_false_and_no_validate_path_produces_applied(self):
        self.assertFalse(is_agentic_workflow_enabled())
        result = self._validate()
        failure = self._validate(None)

        self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)
        self.assertNotEqual(failure.get("status"), WORKFLOW_STATUS_APPLIED)


class AIAgenticRepairIntegrationTests(SimpleTestCase):
    class FakeProvider:
        def __init__(
            self,
            *,
            generate_responses=None,
            full_responses=None,
            section_responses=None,
            generate_exception=None,
            full_exception=None,
            section_exception=None,
            mutate_received=False,
        ):
            self.generate_responses = list(generate_responses or [])
            self.full_responses = list(full_responses or [])
            self.section_responses = list(section_responses or [])
            self.generate_exception = generate_exception
            self.full_exception = full_exception
            self.section_exception = section_exception
            self.mutate_received = mutate_received
            self.analysis_call_count = 0
            self.generate_call_count = 0
            self.regenerate_call_count = 0
            self.regenerate_section_call_count = 0
            self.generate_calls = []
            self.full_calls = []
            self.section_calls = []

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            return AIAgenticRepairIntegrationTests._raw_response(
                {
                    "description_language": "en",
                    "description_sufficient": True,
                    "detected_store_domains": ["beauty"],
                    "business_summary": "A clear beauty store.",
                    "target_audience": "women",
                    "product_direction": ["skincare"],
                    "blocking_missing_information": [],
                    "ambiguities": [],
                }
            )

        def generate_store_draft(self, **kwargs):
            self.generate_call_count += 1
            self.generate_calls.append(deepcopy(kwargs))
            if self.generate_exception is not None:
                raise self.generate_exception
            return self._pop_response(self.generate_responses)

        def generate_agentic_store_draft(self, **kwargs):
            return self.generate_store_draft(**kwargs)

        def regenerate_store_draft(self, **kwargs):
            self.regenerate_call_count += 1
            self.full_calls.append(deepcopy(kwargs))
            self._maybe_mutate_received(kwargs)
            if self.full_exception is not None:
                raise self.full_exception
            return self._pop_response(self.full_responses)

        def regenerate_store_draft_section(self, **kwargs):
            self.regenerate_section_call_count += 1
            self.section_calls.append(deepcopy(kwargs))
            self._maybe_mutate_received(kwargs)
            if self.section_exception is not None:
                raise self.section_exception
            return self._pop_response(self.section_responses)

        def _maybe_mutate_received(self, kwargs):
            if not self.mutate_received:
                return
            current_draft = kwargs.get("current_draft")
            if isinstance(current_draft, dict):
                current_draft.setdefault("store", {})["name"] = "Mutated Provider Draft"
            templates = kwargs.get("available_theme_templates")
            if isinstance(templates, list):
                templates.append("Mutated Provider Template")

        @staticmethod
        def _pop_response(responses):
            if not responses:
                raise RuntimeError("secret provider response queue exhausted at 10.0.0.1")
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return AIAgenticGraphSkeletonTests._valid_full_draft_payload()

    @staticmethod
    def _valid_products() -> list[dict]:
        return deepcopy(AIAgenticGraphSkeletonTests._valid_full_draft_payload()["products"])

    @staticmethod
    def _valid_theme() -> dict:
        return deepcopy(AIAgenticGraphSkeletonTests._valid_full_draft_payload()["theme"])

    @staticmethod
    def _valid_categories() -> list[dict]:
        return deepcopy(AIAgenticGraphSkeletonTests._valid_full_draft_payload()["categories"])

    @staticmethod
    def _raw_response(payload: Any) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    @staticmethod
    def _raw_text_response(text: str) -> dict:
        return {"choices": [{"message": {"content": text}}]}

    @staticmethod
    def _valid_clarification_payload() -> dict:
        return {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

    def _issue(self, code: str, *, repairable=True) -> dict:
        paths = {
            "draft_payload_invalid": "draft_payload",
            "response_mode_invalid": "clarification_questions",
            "clarification_questions_invalid": "clarification_questions",
            "store_section_invalid": "store",
            "store_settings_section_invalid": "store_settings",
            "theme_section_invalid": "theme",
            "theme_template_unavailable": "theme.theme_template",
            "categories_section_invalid": "categories",
            "products_section_invalid": "products",
        }
        return {
            "path": paths.get(code, "draft_payload"),
            "code": code,
            "message": "Repairable validation issue.",
            "repairable": repairable,
        }

    def _repair_kwargs(self, **overrides):
        kwargs = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "normalized_description": "Create a modern skincare store for young women.",
            "expected_mode": "draft_ready",
            "current_draft": self._valid_full_draft_payload(),
            "validation_errors": [self._issue("products_section_invalid")],
            "available_theme_templates": ["Modern"],
            "repair_attempt_count": 0,
        }
        kwargs.update(overrides)
        return kwargs

    def _state(self, **overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Raw user wording should not be used",
            "normalized_description": "Create a modern skincare store for young women.",
            "available_theme_templates": ["Modern"],
            "draft_payload": self._valid_full_draft_payload(),
            "mode": "draft_ready",
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "validation_errors": [self._issue("products_section_invalid")],
        }
        state.update(overrides)
        return state

    def _run_repair_node(self, provider, state=None):
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ) as mock_factory:
            result = repair_node(state or self._state())
        return result, mock_factory

    def _assert_failed_repair_result(self, result):
        self.assertEqual(result["current_step"], "repair")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)
        json.dumps(result)

    def test_adapter_factory_is_lazy_and_once_per_repair_invocation(self):
        with patch("AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client") as mock_factory:
            with self.assertRaises(Exception):
                repairing.repair_draft_payload(
                    **self._repair_kwargs(validation_errors=[])
                )
        mock_factory.assert_not_called()

        provider = self.FakeProvider(
            section_responses=[self._raw_response({"products": self._valid_products()})]
        )
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ) as mock_factory:
            result = repairing.repair_draft_payload(**self._repair_kwargs())

        mock_factory.assert_called_once_with()
        self.assertEqual(provider.regenerate_section_call_count, 1)
        self.assertEqual(result["products"], self._valid_products())

    def test_adapter_requires_strict_expected_mode_before_provider_creation(self):
        invalid_modes = (None, "", "failed_recoverable", " draft_ready ", True, 1, [], {})

        for expected_mode in invalid_modes:
            with self.subTest(expected_mode=expected_mode):
                with patch("AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client") as mock_factory:
                    with self.assertRaises(Exception):
                        repairing.repair_draft_payload(
                            **self._repair_kwargs(expected_mode=expected_mode)
                        )
                mock_factory.assert_not_called()

    def test_adapter_accepts_both_valid_expected_modes(self):
        cases = (
            (
                "draft_ready",
                self.FakeProvider(
                    section_responses=[self._raw_response({"products": self._valid_products()})]
                ),
            ),
            (
                "clarification",
                self.FakeProvider(
                    section_responses=[self._raw_response({"products": self._valid_products()})]
                ),
            ),
        )

        for expected_mode, provider in cases:
            with self.subTest(expected_mode=expected_mode):
                with patch(
                    "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
                    return_value=provider,
                ) as mock_factory:
                    result = repairing.repair_draft_payload(
                        **self._repair_kwargs(expected_mode=expected_mode)
                    )

                mock_factory.assert_called_once_with()
                self.assertEqual(provider.regenerate_section_call_count, 1)
                self.assertEqual(result["products"], self._valid_products())

    def test_provider_context_contains_expected_mode_for_section_and_full_repair(self):
        section_provider = self.FakeProvider(
            section_responses=[self._raw_response({"products": self._valid_products()})]
        )
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=section_provider,
        ):
            repairing.repair_draft_payload(
                **self._repair_kwargs(expected_mode="draft_ready")
            )

        section_context = section_provider.section_calls[0]["clarification_context"]
        self.assertEqual(section_context["expected_mode"], "draft_ready")
        json.dumps(section_context)

        full_provider = self.FakeProvider(
            full_responses=[self._raw_response(self._valid_clarification_payload())]
        )
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=full_provider,
        ):
            repairing.repair_draft_payload(
                **self._repair_kwargs(
                    expected_mode="clarification",
                    current_draft=self._valid_clarification_payload(),
                    validation_errors=[self._issue("clarification_questions_invalid")],
                )
            )

        full_context = full_provider.full_calls[0]["clarification_context"]
        self.assertEqual(full_context["expected_mode"], "clarification")
        json.dumps(full_context)

    def test_section_repair_strategy_for_single_supported_sections(self):
        cases = (
            ("products_section_invalid", "products", {"products": self._valid_products()}),
            ("theme_section_invalid", "theme", {"theme": self._valid_theme()}),
            ("categories_section_invalid", "categories", {"categories": self._valid_categories()}),
        )
        for code, target_section, response_payload in cases:
            with self.subTest(code=code):
                current_draft = self._valid_full_draft_payload()
                provider = self.FakeProvider(
                    section_responses=[self._raw_response(response_payload)]
                )
                with patch(
                    "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
                    return_value=provider,
                ):
                    result = repairing.repair_draft_payload(
                        **self._repair_kwargs(
                            current_draft=current_draft,
                            validation_errors=[self._issue(code)],
                        )
                    )

                self.assertEqual(provider.regenerate_section_call_count, 1)
                self.assertEqual(provider.regenerate_call_count, 0)
                self.assertEqual(provider.section_calls[0]["target_section"], target_section)
                self.assertEqual(result[target_section], response_payload[target_section])
                for section_name in ("store", "store_settings", "theme", "categories", "products"):
                    if section_name != target_section:
                        self.assertEqual(result[section_name], current_draft[section_name])

    def test_theme_section_and_unavailable_template_share_one_theme_section_repair(self):
        provider = self.FakeProvider(
            section_responses=[self._raw_response({"theme": self._valid_theme()})]
        )
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            repairing.repair_draft_payload(
                **self._repair_kwargs(
                    validation_errors=[
                        self._issue("theme_section_invalid"),
                        self._issue("theme_template_unavailable"),
                    ]
                )
            )

        self.assertEqual(provider.regenerate_section_call_count, 1)
        self.assertEqual(provider.section_calls[0]["target_section"], "theme")
        self.assertEqual(provider.regenerate_call_count, 0)

    def test_full_repair_strategy_for_non_section_or_multi_section_issues(self):
        cases = (
            [self._issue("store_section_invalid")],
            [self._issue("store_settings_section_invalid")],
            [self._issue("response_mode_invalid")],
            [self._issue("clarification_questions_invalid")],
            [self._issue("draft_payload_invalid")],
            [self._issue("categories_section_invalid"), self._issue("products_section_invalid")],
            [self._issue("store_section_invalid"), self._issue("theme_section_invalid")],
        )
        for issue_list in cases:
            with self.subTest(codes=[issue["code"] for issue in issue_list]):
                repaired = self._valid_full_draft_payload()
                repaired["store"]["name"] = "Full Repair Store"
                provider = self.FakeProvider(
                    full_responses=[self._raw_response(repaired)]
                )
                with patch(
                    "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
                    return_value=provider,
                ):
                    result = repairing.repair_draft_payload(
                        **self._repair_kwargs(validation_errors=issue_list)
                    )

                self.assertEqual(provider.regenerate_call_count, 1)
                self.assertEqual(provider.regenerate_section_call_count, 0)
                self.assertEqual(result["store"]["name"], "Full Repair Store")

    def test_invalid_repair_inputs_fail_before_provider_creation(self):
        circular_draft = {}
        circular_draft["self"] = circular_draft
        malformed_issue = dict(self._issue("products_section_invalid"))
        malformed_issue["extra"] = "nope"
        cases = (
            {"validation_errors": [self._issue("unknown_repair_code")]},
            {"validation_errors": [self._issue("products_section_invalid", repairable=False)]},
            {"validation_errors": []},
            {"validation_errors": [malformed_issue]},
            {"store_id": 0},
            {"store_id": True},
            {"tenant_id": "101"},
            {"user_id": -1},
            {"normalized_description": "   "},
            {"current_draft": []},
            {"current_draft": circular_draft},
            {"available_theme_templates": []},
            {"available_theme_templates": ["Modern", 123]},
            {"available_theme_templates": ["   "]},
            {"repair_attempt_count": True},
            {"repair_attempt_count": -1},
            {"repair_attempt_count": MAX_REPAIR_ATTEMPTS},
        )

        for overrides in cases:
            with self.subTest(overrides=overrides):
                with patch("AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client") as mock_factory:
                    with self.assertRaises(Exception):
                        repairing.repair_draft_payload(**self._repair_kwargs(**overrides))
                mock_factory.assert_not_called()

    def test_provider_receives_safe_context_and_defensive_copies(self):
        current_draft = self._valid_full_draft_payload()
        validation_errors = [self._issue("products_section_invalid")]
        theme_templates = ["  Modern  ", "Classic", "Modern", "  Classic  "]
        provider = self.FakeProvider(
            section_responses=[self._raw_response({"products": self._valid_products()})],
            mutate_received=True,
        )

        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = repairing.repair_draft_payload(
                **self._repair_kwargs(
                    normalized_description="Trusted normalized description",
                    current_draft=current_draft,
                    validation_errors=validation_errors,
                    available_theme_templates=theme_templates,
                )
            )

        call = provider.section_calls[0]
        context = call["clarification_context"]
        self.assertEqual(call["original_store_description"], "Trusted normalized description")
        self.assertNotIn("Raw user wording should not be used", json.dumps(call))
        self.assertEqual(call["available_theme_templates"], ["Modern", "Classic"])
        self.assertEqual(theme_templates, ["  Modern  ", "Classic", "Modern", "  Classic  "])
        self.assertEqual(context["operation"], "agentic_validation_repair")
        self.assertEqual(context["expected_mode"], "draft_ready")
        self.assertEqual(context["repair_attempt_count"], 1)
        self.assertEqual(context["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)
        self.assertEqual(context["validation_errors"], validation_errors)
        self.assertIsInstance(context["repair_instruction"], str)
        self.assertNotIn("Exception", json.dumps(context))
        self.assertEqual(current_draft["store"]["name"], "My Store")
        self.assertEqual(validation_errors[0]["message"], "Repairable validation issue.")
        self.assertEqual(result["store"]["name"], "My Store")

    def test_section_repair_rejects_malformed_section_payloads_safely(self):
        cases = (
            {"products": self._valid_products(), "theme": self._valid_theme()},
            {"theme": self._valid_theme()},
            self._valid_full_draft_payload(),
        )
        for response_payload in cases:
            with self.subTest(keys=list(response_payload.keys())):
                provider = self.FakeProvider(
                    section_responses=[self._raw_response(response_payload)]
                )
                result, mock_factory = self._run_repair_node(provider)

                mock_factory.assert_called_once_with()
                self._assert_failed_repair_result(result)
                self.assertEqual(result["repair_attempt_count"], 1)
                serialized = json.dumps(result)
                self.assertNotIn("Partial regeneration payload", serialized)
                self.assertNotIn("choices", serialized)

    def test_full_repair_rejects_non_mapping_parse_result_safely(self):
        provider = self.FakeProvider(
            full_responses=[self._raw_text_response("[]")]
        )
        result, _mock_factory = self._run_repair_node(
            provider,
            self._state(validation_errors=[self._issue("store_section_invalid")]),
        )

        self._assert_failed_repair_result(result)
        self.assertEqual(provider.regenerate_call_count, 2)
        self.assertNotIn("Provider JSON content", json.dumps(result))

    def test_targeted_prevalidation_normalization_runs_on_repaired_candidate(self):
        products = self._valid_products()
        products[0].pop("image_url")
        provider = self.FakeProvider(
            section_responses=[self._raw_response({"products": products})]
        )

        result, _mock_factory = self._run_repair_node(provider)

        self.assertEqual(result["route_decision"], "validate")
        self.assertEqual(result["draft_payload"]["products"][0]["image_url"], "")
        json.dumps(result["draft_payload"])

    def test_repair_node_success_partial_update_contract(self):
        state = self._state()
        before = deepcopy(state)
        provider = self.FakeProvider(
            section_responses=[self._raw_response({"products": self._valid_products()})]
        )

        result, mock_factory = self._run_repair_node(provider, state)

        mock_factory.assert_called_once_with()
        self.assertEqual(state, before)
        self.assertEqual(result["current_step"], "repair")
        self.assertEqual(result["status"], WORKFLOW_STATUS_PROCESSING)
        self.assertEqual(result["route_decision"], "validate")
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(result["draft_payload"]["products"], self._valid_products())
        self.assertNotIn("mode", result)
        self.assertNotIn("validation_errors", result)
        self.assertNotIn("clarification_questions", result)
        self.assertNotIn("clarification_round_count", result)
        self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)
        self.assertNotIn("choices", json.dumps(result))

    def test_repair_node_passes_state_mode_to_adapter(self):
        for mode in ("draft_ready", "clarification"):
            with self.subTest(mode=mode):
                with patch(
                    "AI_Store_Creation_Service.agentic.nodes.repair.repair_draft_payload",
                    return_value=self._valid_full_draft_payload(),
                ) as mock_adapter:
                    result = repair_node(self._state(mode=mode))

                self.assertEqual(result["route_decision"], "validate")
                self.assertNotIn("mode", result)
                self.assertEqual(mock_adapter.call_args.kwargs["expected_mode"], mode)

    def test_repair_node_failure_contract_and_safe_messages(self):
        provider = self.FakeProvider(
            section_exception=RuntimeError("secret provider database redis detail at 10.0.0.1")
        )

        result, mock_factory = self._run_repair_node(provider)

        mock_factory.assert_called_once_with()
        self._assert_failed_repair_result(result)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(result["draft_payload"], self._valid_full_draft_payload())
        self.assertEqual(result["validation_errors"], [self._issue("products_section_invalid")])
        serialized = json.dumps(result)
        self.assertNotIn("secret provider database redis detail", serialized)
        self.assertNotIn("10.0.0.1", serialized)
        self.assertEqual(provider.regenerate_section_call_count, 1)

    def test_success_update_non_serializable_candidate_is_caught(self):
        state = self._state()
        with patch(
            "AI_Store_Creation_Service.agentic.nodes.repair.repair_draft_payload",
            return_value={"bad": object()},
        ):
            result = repair_node(state)

        self._assert_failed_repair_result(result)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(result["draft_payload"], state["draft_payload"])
        serialized = json.dumps(result)
        self.assertNotIn("object at", serialized)

    def test_success_update_circular_candidate_is_caught(self):
        candidate = {}
        candidate["self"] = candidate

        with patch(
            "AI_Store_Creation_Service.agentic.nodes.repair.repair_draft_payload",
            return_value=candidate,
        ):
            result = repair_node(self._state())

        self._assert_failed_repair_result(result)
        self.assertEqual(result["repair_attempt_count"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("Circular reference detected", serialized)

    def test_success_update_deepcopy_failure_is_caught(self):
        class DeepcopyFailure:
            def __deepcopy__(self, memo):
                raise RuntimeError("secret deepcopy failure")

        with patch(
            "AI_Store_Creation_Service.agentic.nodes.repair.repair_draft_payload",
            return_value=DeepcopyFailure(),
        ):
            result = repair_node(self._state())

        self._assert_failed_repair_result(result)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertNotIn("secret deepcopy failure", json.dumps(result))

    def test_invalid_counter_fails_without_increment_or_provider_creation(self):
        for invalid_count, expected_count in (
            (True, 0),
            (-1, 0),
            ("1", 0),
            (MAX_REPAIR_ATTEMPTS, MAX_REPAIR_ATTEMPTS),
            (MAX_REPAIR_ATTEMPTS + 5, MAX_REPAIR_ATTEMPTS),
        ):
            with self.subTest(invalid_count=invalid_count):
                with patch("AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client") as mock_factory:
                    result = repair_node(self._state(repair_attempt_count=invalid_count))

                mock_factory.assert_not_called()
                self._assert_failed_repair_result(result)
                self.assertEqual(result["repair_attempt_count"], expected_count)

    def test_invalid_expected_mode_fails_closed_in_node_without_provider_creation(self):
        for mode in (None, "failed_recoverable", True):
            with self.subTest(mode=mode):
                with patch("AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client") as mock_factory:
                    result = repair_node(self._state(mode=mode, repair_attempt_count=0))

                mock_factory.assert_not_called()
                self._assert_failed_repair_result(result)
                self.assertEqual(result["repair_attempt_count"], 1)
                serialized = json.dumps(result)
                self.assertNotIn("Repair expected mode is invalid", serialized)

    def test_parse_retry_uses_same_repair_attempt_counter_once(self):
        provider = self.FakeProvider(
            section_responses=[
                self._raw_text_response("not-json"),
                self._raw_response({"products": self._valid_products()}),
            ]
        )

        result, mock_factory = self._run_repair_node(provider)

        mock_factory.assert_called_once_with()
        self.assertEqual(provider.regenerate_section_call_count, 2)
        self.assertEqual(result["route_decision"], "validate")
        self.assertEqual(result["repair_attempt_count"], 1)

    def test_parse_failure_twice_returns_safe_failure(self):
        provider = self.FakeProvider(
            section_responses=[
                self._raw_text_response("not-json"),
                self._raw_text_response("still-not-json"),
            ]
        )

        result, _mock_factory = self._run_repair_node(provider)

        self._assert_failed_repair_result(result)
        self.assertEqual(provider.regenerate_section_call_count, 2)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertNotIn("not valid JSON", json.dumps(result))

    def test_provider_factory_failure_returns_safe_failure(self):
        with patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            side_effect=RuntimeError("secret factory provider detail"),
        ) as mock_factory:
            result = repair_node(self._state())

        mock_factory.assert_called_once_with()
        self._assert_failed_repair_result(result)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertNotIn("secret factory provider detail", json.dumps(result))

    def test_provider_invocation_failure_does_not_retry(self):
        provider = self.FakeProvider(section_exception=RuntimeError("secret provider detail"))

        result, _mock_factory = self._run_repair_node(provider)

        self._assert_failed_repair_result(result)
        self.assertEqual(provider.regenerate_section_call_count, 1)
        self.assertNotIn("secret provider detail", json.dumps(result))

    def test_response_mode_repair_chain_preserves_draft_ready_mode(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["clarification_needed"] = False
        invalid_payload["clarification_questions"] = [
            {
                "question_key": "store_type",
                "question_text": "What type of store?",
                "options": ["Fashion", "Electronics"],
            }
        ]
        provider = self.FakeProvider(
            full_responses=[self._raw_response(self._valid_full_draft_payload())]
        )
        state = self._state(
            mode="draft_ready",
            draft_payload=invalid_payload,
            validation_errors=[self._issue("response_mode_invalid")],
            repair_attempt_count=0,
        )

        repair_update, _mock_factory = self._run_repair_node(provider, state)
        repaired_state = {**state, **repair_update}
        validate_update = validate_node(repaired_state)

        self.assertEqual(provider.regenerate_call_count, 1)
        self.assertEqual(provider.regenerate_section_call_count, 0)
        self.assertEqual(provider.full_calls[0]["clarification_context"]["expected_mode"], "draft_ready")
        self.assertNotIn("mode", repair_update)
        self.assertEqual(repaired_state["mode"], "draft_ready")
        self.assertEqual(repair_update["repair_attempt_count"], 1)
        self.assertEqual(validate_update["route_decision"], "human_review")
        self.assertEqual(validate_update["mode"], "draft_ready")
        self.assertEqual(validate_update["validation_errors"], [])
        self.assertNotIn("state_mode_mismatch", json.dumps(validate_update))

    def test_clarification_repair_chain_preserves_clarification_mode(self):
        invalid_payload = self._valid_clarification_payload()
        invalid_payload["clarification_questions"][0]["options"] = ["Only one"]
        provider = self.FakeProvider(
            full_responses=[self._raw_response(self._valid_clarification_payload())]
        )
        state = self._state(
            mode="clarification",
            draft_payload=invalid_payload,
            validation_errors=[self._issue("clarification_questions_invalid")],
            repair_attempt_count=0,
        )

        repair_update, _mock_factory = self._run_repair_node(provider, state)
        repaired_state = {**state, **repair_update}
        validate_update = validate_node(repaired_state)

        self.assertEqual(provider.regenerate_call_count, 1)
        self.assertEqual(provider.full_calls[0]["clarification_context"]["expected_mode"], "clarification")
        self.assertNotIn("mode", repair_update)
        self.assertEqual(repaired_state["mode"], "clarification")
        self.assertEqual(repair_update["repair_attempt_count"], 1)
        self.assertEqual(validate_update["route_decision"], "human_review")
        self.assertEqual(validate_update["mode"], "clarification")
        self.assertEqual(validate_update["validation_errors"], [])
        self.assertTrue(validate_update["draft_payload"]["clarification_needed"])
        self.assertTrue(validate_update["clarification_questions"])
        self.assertNotIn("state_mode_mismatch", json.dumps(validate_update))

    def test_repair_node_does_not_call_validate_adapter_directly(self):
        source = inspect.getsource(repairing) + inspect.getsource(repair_node)

        self.assertNotIn("validate_generated_draft", source)
        self.assertNotIn("validate_basic_draft_schema", source)
        self.assertNotIn("detect_ai_response_mode", source)
        self.assertNotIn("validate_store_section", source)
        self.assertNotIn("validate_products_section", source)

    def test_repair_source_boundaries_do_not_reference_forbidden_systems(self):
        adapter_source = inspect.getsource(repairing)
        node_source = inspect.getsource(repair_node)
        combined_source = adapter_source + node_source

        for forbidden_reference in (
            "Store.objects",
            "ThemeTemplate.objects",
            "selectors",
            "draft_store",
            "save_ai_draft",
            "save_ai_draft_meta",
            "metadata_services",
            "workflow_services",
            "services",
            "apply_services",
            "Redis",
            "cache",
            "requests",
            "APIClient",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, combined_source)
        self.assertIn("get_ai_provider_client", adapter_source)
        self.assertNotIn("get_ai_provider_client", node_source)

    def test_graph_successful_repair_from_first_attempt(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["products"][0]["price"] = 0
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            section_responses=[self._raw_response({"products": self._valid_products()})],
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        self.assertEqual(provider.generate_call_count, 1)
        self.assertEqual(provider.regenerate_section_call_count, 1)
        self.assertEqual(provider.regenerate_call_count, 0)
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(result["validation_errors"], [])

    def test_graph_second_repair_attempt_can_succeed_after_first_invalid_candidate(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["products"][0]["price"] = 0
        still_invalid_products = self._valid_products()
        still_invalid_products[0]["price"] = 0
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            section_responses=[
                self._raw_response({"products": still_invalid_products}),
                self._raw_response({"products": self._valid_products()}),
            ],
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["repair_attempt_count"], 2)
        self.assertEqual(provider.regenerate_section_call_count, 2)
        self.assertEqual(result["validation_errors"], [])

    def test_graph_exhausts_repair_attempts_without_exceeding_limit(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["products"][0]["price"] = 0
        still_invalid_products = self._valid_products()
        still_invalid_products[0]["price"] = 0
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            section_responses=[
                self._raw_response({"products": still_invalid_products})
                for _index in range(MAX_REPAIR_ATTEMPTS)
            ],
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        codes = [issue["code"] for issue in result["validation_errors"]]
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["repair_attempt_count"], MAX_REPAIR_ATTEMPTS)
        self.assertEqual(provider.regenerate_section_call_count, MAX_REPAIR_ATTEMPTS)
        self.assertIn("products_section_invalid", codes)
        self.assertNotIn("state_mode_mismatch", codes)

    def test_graph_repair_provider_failure_stops_safely(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["products"][0]["price"] = 0
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            section_exception=RuntimeError("secret provider repair failure at 10.0.0.1"),
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(provider.regenerate_section_call_count, 1)
        self.assertNotIn("secret provider repair failure", json.dumps(result))
        self.assertNotIn("10.0.0.1", json.dumps(result))

    def test_graph_parse_retry_during_repair_does_not_increment_counter_twice(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["products"][0]["price"] = 0
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            section_responses=[
                self._raw_text_response("not-json"),
                self._raw_response({"products": self._valid_products()}),
            ],
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(provider.regenerate_section_call_count, 2)

    def test_graph_multiple_section_issues_use_full_repair_then_validate(self):
        invalid_payload = self._valid_full_draft_payload()
        invalid_payload["store"] = {"description": "Missing name"}
        invalid_payload["products"][0]["price"] = 0
        repaired = self._valid_full_draft_payload()
        repaired["store"]["name"] = "Full Repair Store"
        provider = self.FakeProvider(
            generate_responses=[self._raw_response(invalid_payload)],
            full_responses=[self._raw_response(repaired)],
        )

        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.repairing.get_ai_provider_client",
            return_value=provider,
        ):
            result = compile_agentic_graph().invoke(self._state())

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["repair_attempt_count"], 1)
        self.assertEqual(provider.regenerate_call_count, 1)
        self.assertEqual(provider.regenerate_section_call_count, 0)
        self.assertEqual(result["draft_payload"]["store"]["name"], "Full Repair Store")

    def test_phase_1h_isolated_from_production_and_graph_contracts(self):
        self.assertFalse(is_agentic_workflow_enabled())
        self.assertIsNone(getattr(compile_agentic_graph(), "checkpointer", None))
        services_source = inspect.getsource(services)
        workflow_source = inspect.getsource(workflow_services)

        self.assertNotIn("agentic.runner", services_source)
        self.assertNotIn("run_agentic_workflow", services_source)
        self.assertNotIn("compile_agentic_graph", workflow_source)
        self.assertNotIn("build_agentic_graph", workflow_source)
        self.assertNotIn("apply_current_ai_draft", inspect.getsource(repairing))
        self.assertNotIn("applied", inspect.getsource(repairing) + inspect.getsource(repair_node))


class AIAgenticRunnerTests(SimpleTestCase):
    class FakeProvider:
        def __init__(self, payload, analysis_payload=None, clarification_payload=None):
            self.payload = payload
            self.analysis_payload = analysis_payload or {
                "description_language": "en",
                "description_sufficient": True,
                "detected_store_domains": ["beauty"],
                "business_summary": "A clear beauty store.",
                "target_audience": "young women",
                "product_direction": ["skincare"],
                "blocking_missing_information": [],
                "ambiguities": [],
            }
            blocking_keys = self.analysis_payload.get("blocking_missing_information") or []
            default_question_key = blocking_keys[0] if blocking_keys else "store_domain"
            self.clarification_payload = (
                clarification_payload
                or AIAgenticRunnerTests._clarification_questions_payload(
                    question_key=default_question_key
                )
            )
            self.analysis_call_count = 0
            self.generate_call_count = 0
            self.clarification_call_count = 0

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            return AIAgenticRunnerTests._as_provider_response(self.analysis_payload)

        def generate_store_draft(self, **kwargs):
            self.generate_call_count += 1
            return AIAgenticRunnerTests._as_provider_response(self.payload)

        def generate_agentic_store_draft(self, **kwargs):
            return self.generate_store_draft(**kwargs)

        def generate_clarification_questions(self, **kwargs):
            self.clarification_call_count += 1
            return AIAgenticRunnerTests._as_provider_response(
                self.clarification_payload
            )

    class FakeCompiledGraph:
        def __init__(self, result=None, exception=None, mutate_state=False):
            self.result = result
            self.exception = exception
            self.mutate_state = mutate_state
            self.invoke_count = 0
            self.received_state = None
            self.received_config = None

        def invoke(self, state, config=None):
            self.invoke_count += 1
            self.received_state = state
            self.received_config = config
            if self.mutate_state:
                state["available_theme_templates"].append("Mutated")
                state["validation_errors"][0]["message"] = "Mutated"
            if self.exception is not None:
                raise self.exception
            return deepcopy(self.result)

    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return AIAgenticGraphSkeletonTests._valid_full_draft_payload()

    @staticmethod
    def _clarification_payload() -> dict:
        return {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

    @staticmethod
    def _clarification_questions_payload(
        *,
        question_key="store_domain",
        question_text="What should the store sell?",
    ) -> dict:
        return {
            "clarification_questions": [
                {
                    "question_key": question_key,
                    "question_text": question_text,
                    "options": ["Coffee", "Fashion"],
                }
            ]
        }

    @staticmethod
    def _analysis_clarification_payload(
        *,
        language="en",
        blocking_key="store_domain",
    ) -> dict:
        return {
            "description_language": language,
            "description_sufficient": False,
            "detected_store_domains": [],
            "business_summary": "The store idea needs clarification.",
            "target_audience": "",
            "product_direction": [],
            "blocking_missing_information": [blocking_key],
            "ambiguities": ["The core store direction is missing."],
        }

    def _run(
        self,
        description="Create a modern skincare store for young women.",
        analysis_payload=None,
        clarification_payload=None,
        **overrides,
    ):
        payload = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": description,
            "normalized_description": description,
            "available_theme_templates": ["Modern"],
        }
        payload.update(overrides)
        fake_provider = self.FakeProvider(
            self._valid_full_draft_payload(),
            analysis_payload=analysis_payload,
            clarification_payload=clarification_payload,
        )
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=fake_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=fake_provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=fake_provider,
        ):
            return run_agentic_workflow(**payload)

    def _ready_terminal_state(self, **overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a coffee store for customers",
            "normalized_description": "Create a coffee store for customers",
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "draft_ready",
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "route_decision": "human_review",
            "clarification_questions": [],
            "draft_payload": self._valid_full_draft_payload(),
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _clarification_terminal_state(self, **overrides):
        state = {
            "workflow_entry": "clarification_resume",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "I want an online store",
            "normalized_description": "I want an online store",
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "clarification",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "route_decision": "human_review",
            "clarification_questions": self._clarification_payload()[
                "clarification_questions"
            ],
            "draft_payload": self._clarification_payload(),
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _failed_terminal_state(self, **overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a coffee store for customers",
            "normalized_description": "Create a coffee store for customers",
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "recoverable_failure",
            "mode": "failed_recoverable",
            "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
            "route_decision": "failed_recoverable",
            "clarification_questions": [],
            "error_code": "provider_timeout",
            "user_message": "Provider timeout at 10.0.0.1 in internal.module",
            "draft_payload": {},
        }
        state.update(overrides)
        return state

    def _run_with_fake_graph(self, fake_graph, **overrides):
        payload = {
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "Create a coffee store for customers",
            "normalized_description": "Create a coffee store for customers",
        }
        payload.update(overrides)
        with patch(
            "AI_Store_Creation_Service.agentic.runner.compile_agentic_graph",
            return_value=fake_graph,
        ) as mock_compile:
            result = run_agentic_workflow(**payload)
        return result, mock_compile

    def _assert_safe_failure(self, result):
        self.assertEqual(result["current_step"], "recoverable_failure")
        self.assertEqual(result["mode"], "failed_recoverable")
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["route_decision"], "failed_recoverable")
        self.assertEqual(result["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertEqual(result["clarification_questions"], [])
        self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)
        json.dumps(result)

    def test_build_initial_agent_state_returns_plain_dict_with_required_fields(self):
        state = build_initial_agent_state(
            store_id=10,
            tenant_id=101,
            user_id=7,
            user_store_description="Original idea",
            normalized_description="Normalized idea",
        )

        self.assertIs(type(state), dict)
        self.assertEqual(state["store_id"], 10)
        self.assertEqual(state["tenant_id"], 101)
        self.assertEqual(state["user_id"], 7)
        self.assertEqual(state["user_store_description"], "Original idea")
        self.assertEqual(state["normalized_description"], "Normalized idea")
        self.assertEqual(state["workflow_entry"], "fresh")
        self.assertEqual(state["clarification_round_count"], 0)
        self.assertEqual(state["clarification_history"], [])
        self.assertEqual(state["clarification_facts"], {})
        self.assertEqual(state["repair_attempt_count"], 0)
        self.assertNotIn("route_decision", state)
        self.assertNotIn("status", state)

    def test_build_initial_agent_state_defensively_copies_mutable_values(self):
        templates = ["Modern", "Classic"]
        validation_errors = [
            {
                "path": "products.0.price",
                "code": "invalid_price",
                "message": "Product price must be positive.",
                "repairable": True,
            }
        ]

        state = build_initial_agent_state(
            store_id=10,
            tenant_id=101,
            user_id=7,
            user_store_description="Original idea",
            normalized_description="Normalized idea",
            available_theme_templates=templates,
            validation_errors=validation_errors,
        )

        templates.append("Mutated")
        validation_errors[0]["message"] = "Mutated"
        state["available_theme_templates"].append("State only")
        state["validation_errors"][0]["code"] = "state_only"

        self.assertEqual(templates, ["Modern", "Classic", "Mutated"])
        self.assertEqual(validation_errors[0]["message"], "Mutated")
        self.assertEqual(
            state["available_theme_templates"],
            ["Modern", "Classic", "State only"],
        )
        self.assertEqual(
            state["validation_errors"][0]["message"],
            "Product price must be positive.",
        )

    def test_build_initial_agent_state_defensively_copies_mutable_core_values(self):
        store_id = {"value": [10]}
        user_store_description = ["original", {"nested": ["value"]}]
        normalized_description = {"text": ["description"]}
        clarification_round_count = {"count": [1]}

        state = build_initial_agent_state(
            store_id=store_id,
            tenant_id=101,
            user_id=7,
            user_store_description=user_store_description,
            normalized_description=normalized_description,
            clarification_round_count=clarification_round_count,
            repair_attempt_count=0,
        )

        store_id["value"].append(11)
        user_store_description[1]["nested"].append("caller")
        normalized_description["text"].append("caller")
        clarification_round_count["count"].append(2)

        self.assertEqual(state["store_id"], {"value": [10]})
        self.assertEqual(
            state["user_store_description"],
            ["original", {"nested": ["value"]}],
        )
        self.assertEqual(state["normalized_description"], {"text": ["description"]})
        self.assertEqual(state["clarification_round_count"], {"count": [1]})

        state["store_id"]["value"].append(12)
        state["user_store_description"][1]["nested"].append("state")
        state["normalized_description"]["text"].append("state")
        state["clarification_round_count"]["count"].append(3)

        self.assertEqual(store_id, {"value": [10, 11]})
        self.assertEqual(
            user_store_description,
            ["original", {"nested": ["value", "caller"]}],
        )
        self.assertEqual(
            normalized_description,
            {"text": ["description", "caller"]},
        )
        self.assertEqual(clarification_round_count, {"count": [1, 2]})

    def test_build_initial_agent_state_preserves_normal_scalar_values(self):
        state = build_initial_agent_state(
            store_id=10,
            tenant_id=101,
            user_id=7,
            user_store_description="Original idea",
            normalized_description="Normalized idea",
            clarification_round_count=2,
            repair_attempt_count=1,
        )

        self.assertEqual(state["store_id"], 10)
        self.assertEqual(state["tenant_id"], 101)
        self.assertEqual(state["user_id"], 7)
        self.assertEqual(state["user_store_description"], "Original idea")
        self.assertEqual(state["normalized_description"], "Normalized idea")
        self.assertEqual(state["clarification_round_count"], 2)
        self.assertEqual(state["repair_attempt_count"], 1)

    def test_clear_english_description_reaches_ready_for_review(self):
        result = self._run("Create a modern skincare store for young women.")

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["mode"], "draft_ready")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["clarification_questions"], [])
        json.dumps(result)

    def test_clear_arabic_description_reaches_ready_for_review(self):
        description = (
            "\u0623\u0631\u064a\u062f \u0645\u062a\u062c\u0631\u0627 "
            "\u0644\u0628\u064a\u0639 \u0627\u0644\u0642\u0647\u0648\u0629 "
            "\u0627\u0644\u0645\u062e\u062a\u0635\u0629"
        )

        result = self._run(
            description,
            analysis_payload={
                "description_language": "ar",
                "description_sufficient": True,
                "detected_store_domains": ["coffee"],
                "business_summary": "\u0645\u062a\u062c\u0631 \u0642\u0647\u0648\u0629 \u0645\u062e\u062a\u0635\u0629.",
                "target_audience": "",
                "product_direction": ["specialty coffee"],
                "blocking_missing_information": [],
                "ambiguities": [],
            },
        )

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["mode"], "draft_ready")
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["route_decision"], "human_review")
        self.assertEqual(result["description_language"], "ar")

    def test_vague_description_reaches_needs_clarification_without_generation(self):
        result = self._run(
            "I want to create a beautiful online store.",
            analysis_payload=self._analysis_clarification_payload(),
        )

        self.assertEqual(result["current_step"], "human_review")
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertTrue(result["draft_payload"]["clarification_needed"])
        self.assertEqual(result["validation_errors"], [])

    def test_unknown_description_can_reach_needs_clarification_when_ai_asks(self):
        result = self._run(
            "\u060c\u060c\u060c!!!",
            analysis_payload=self._analysis_clarification_payload(
                language="unknown",
                blocking_key="description_language",
            ),
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(
            result["clarification_questions"][0]["question_key"],
            "description_language",
        )

    def test_invalid_identity_values_reach_failed_recoverable(self):
        for field in ("store_id", "tenant_id", "user_id"):
            with self.subTest(field=field):
                result = self._run(**{field: 0})

                self._assert_safe_failure(result)

    def test_compiled_graph_is_invoked_exactly_once(self):
        fake_graph = self.FakeCompiledGraph(self._ready_terminal_state())

        result, mock_compile = self._run_with_fake_graph(fake_graph)

        mock_compile.assert_called_once_with()
        self.assertEqual(fake_graph.invoke_count, 1)
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertIsInstance(fake_graph.received_state, dict)
        self.assertGreater(fake_graph.received_config["recursion_limit"], 10)

    def test_compile_agentic_graph_is_lazy_and_not_called_by_builder_or_import(self):
        with patch(
            "AI_Store_Creation_Service.agentic.runner.compile_agentic_graph"
        ) as mock_compile:
            build_initial_agent_state(
                store_id=10,
                tenant_id=101,
                user_id=7,
                user_store_description="Original idea",
                normalized_description="Normalized idea",
            )
            mock_compile.assert_not_called()

        module_name = "AI_Store_Creation_Service.agentic.runner"
        package = sys.modules["AI_Store_Creation_Service.agentic"]
        previous_module = sys.modules.pop(module_name, None)
        previous_attribute = getattr(package, "runner", None)
        try:
            with patch(
                "AI_Store_Creation_Service.agentic.graph.compile_agentic_graph"
            ) as mock_graph_compile:
                importlib.import_module(module_name)
                mock_graph_compile.assert_not_called()
        finally:
            if previous_module is not None:
                sys.modules[module_name] = previous_module
            if previous_attribute is not None:
                setattr(package, "runner", previous_attribute)

    def test_graph_compilation_exception_returns_safe_failed_recoverable(self):
        with patch(
            "AI_Store_Creation_Service.agentic.runner.compile_agentic_graph",
            side_effect=RuntimeError("secret compile failure"),
        ):
            result = self._run()

        self._assert_safe_failure(result)
        self.assertNotIn("secret compile failure", json.dumps(result))

    def test_graph_invocation_exception_returns_safe_failed_recoverable(self):
        fake_graph = self.FakeCompiledGraph(
            exception=RuntimeError("secret invoke failure")
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)
        self.assertEqual(fake_graph.invoke_count, 1)
        self.assertNotIn("secret invoke failure", json.dumps(result))

    def test_technical_graph_failure_text_is_canonicalized(self):
        fake_graph = self.FakeCompiledGraph(self._failed_terminal_state())

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)
        serialized_result = json.dumps(result).lower()
        self.assertNotIn("provider_timeout", serialized_result)
        self.assertNotIn("provider timeout", serialized_result)
        self.assertNotIn("10.0.0.1", serialized_result)
        self.assertNotIn("internal.module", serialized_result)

    def test_database_failure_details_are_not_returned(self):
        fake_graph = self.FakeCompiledGraph(
            self._failed_terminal_state(
                error_code="database_failure",
                user_message="OperationalError: no such table stores_store",
            )
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)
        serialized_result = json.dumps(result)
        self.assertNotIn("OperationalError", serialized_result)
        self.assertNotIn("no such table", serialized_result)
        self.assertNotIn("stores_store", serialized_result)

    def test_redis_or_cache_failure_details_are_not_returned(self):
        fake_graph = self.FakeCompiledGraph(
            self._failed_terminal_state(
                error_code="redis_connection_failed",
                user_message="Redis connection failed at redis://localhost:6379",
            )
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)
        serialized_result = json.dumps(result).lower()
        self.assertNotIn("redis_connection_failed", serialized_result)
        self.assertNotIn("redis connection failed", serialized_result)
        self.assertNotIn("redis://localhost:6379", serialized_result)

    def test_non_mapping_graph_result_fails_closed(self):
        fake_graph = self.FakeCompiledGraph(["not", "a", "mapping"])

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)

    def test_graph_result_containing_applied_status_fails_closed(self):
        fake_graph = self.FakeCompiledGraph(
            self._ready_terminal_state(status=WORKFLOW_STATUS_APPLIED)
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)

    def test_malformed_human_review_result_fails_closed(self):
        fake_graph = self.FakeCompiledGraph(
            self._ready_terminal_state(mode="clarification")
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)

    def test_needs_clarification_without_valid_mcq_questions_fails_closed(self):
        invalid_question_cases = (
            [],
            [{"question_key": "domain"}],
            [
                {
                    "question_key": "domain",
                    "question_text": "Choose a domain",
                    "options": ["Only one"],
                }
            ],
        )

        for questions in invalid_question_cases:
            with self.subTest(questions=questions):
                fake_graph = self.FakeCompiledGraph(
                    self._clarification_terminal_state(
                        clarification_questions=questions
                    )
                )

                result, _mock_compile = self._run_with_fake_graph(fake_graph)

                self._assert_safe_failure(result)

    def test_non_json_serializable_graph_result_fails_closed(self):
        fake_graph = self.FakeCompiledGraph(
            self._ready_terminal_state(non_serializable=object())
        )

        result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self._assert_safe_failure(result)

    def test_runner_does_not_mutate_initial_mutable_arguments(self):
        templates = ["Modern", "Classic"]
        validation_errors = [
            {
                "path": "products.0.price",
                "code": "invalid_price",
                "message": "Product price must be positive.",
                "repairable": True,
            }
        ]
        fake_graph = self.FakeCompiledGraph(
            self._ready_terminal_state(),
            mutate_state=True,
        )

        result, _mock_compile = self._run_with_fake_graph(
            fake_graph,
            available_theme_templates=templates,
            validation_errors=validation_errors,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(templates, ["Modern", "Classic"])
        self.assertEqual(
            validation_errors[0]["message"],
            "Product price must be positive.",
        )

    def test_fallback_preserves_independent_counters_without_incrementing(self):
        fake_graph = self.FakeCompiledGraph(exception=RuntimeError("counter failure"))

        result, _mock_compile = self._run_with_fake_graph(
            fake_graph,
            clarification_round_count=2,
            repair_attempt_count=1,
        )

        self._assert_safe_failure(result)
        self.assertEqual(result["clarification_round_count"], 2)
        self.assertEqual(result["repair_attempt_count"], 1)

    def test_fallback_normalizes_malformed_counters_and_caps_repair_attempts(self):
        negative_graph = self.FakeCompiledGraph(exception=RuntimeError("counter failure"))
        negative_result, _mock_compile = self._run_with_fake_graph(
            negative_graph,
            clarification_round_count=-1,
            repair_attempt_count="2",
        )

        self._assert_safe_failure(negative_result)
        self.assertEqual(negative_result["clarification_round_count"], 0)
        self.assertEqual(negative_result["repair_attempt_count"], 0)

        excessive_graph = self.FakeCompiledGraph(exception=RuntimeError("counter failure"))
        excessive_result, _mock_compile = self._run_with_fake_graph(
            excessive_graph,
            repair_attempt_count=MAX_REPAIR_ATTEMPTS + 100,
        )

        self._assert_safe_failure(excessive_result)
        self.assertEqual(excessive_result["repair_attempt_count"], MAX_REPAIR_ATTEMPTS)

    def test_successful_and_failed_runner_results_are_json_serializable(self):
        ready_result = self._run("Create a modern skincare store for young women.")
        failed_result = self._run(store_id=0)

        json.dumps(ready_result)
        json.dumps(failed_result)

    def test_runner_source_does_not_reference_external_boundaries(self):
        runner_source = inspect.getsource(runner)
        for forbidden_reference in (
            "providers",
            "models",
            "selectors",
            "draft_store",
            "workflow_services",
            "services",
            "apply_services",
            "Redis",
            "cache",
            "requests",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, runner_source)

    def test_no_runner_path_produces_applied(self):
        ready_result = self._run("Create a modern skincare store for young women.")
        failed_result = self._run(store_id=0)
        fake_graph = self.FakeCompiledGraph(
            self._ready_terminal_state(status=WORKFLOW_STATUS_APPLIED)
        )
        closed_result, _mock_compile = self._run_with_fake_graph(fake_graph)

        self.assertNotEqual(ready_result.get("status"), WORKFLOW_STATUS_APPLIED)
        self.assertNotEqual(failed_result.get("status"), WORKFLOW_STATUS_APPLIED)
        self.assertNotEqual(closed_result.get("status"), WORKFLOW_STATUS_APPLIED)

    def test_feature_flag_still_defaults_to_false(self):
        self.assertFalse(is_agentic_workflow_enabled())

    def test_services_and_workflow_services_remain_unconnected_to_runner(self):
        services_source = inspect.getsource(services)
        workflow_source = inspect.getsource(workflow_services)

        self.assertNotIn("agentic.runner", services_source)
        self.assertNotIn("agentic.runner", workflow_source)
        self.assertNotIn("run_agentic_workflow", services_source)
        self.assertNotIn("run_agentic_workflow", workflow_source)


class AIAgenticClarificationResumeTests(SimpleTestCase):
    class FakeResumeProvider:
        def __init__(
            self,
            *,
            analysis_payload,
            draft_payload=None,
            clarification_payload=None,
        ):
            self.analysis_payload = analysis_payload
            self.draft_payload = draft_payload or AIAgenticGraphSkeletonTests._valid_full_draft_payload()
            self.clarification_payload = clarification_payload or {
                "clarification_questions": [
                    {
                        "question_key": "product_direction",
                        "question_text": "What products should the store focus on?",
                        "options": ["Beans", "Drinks"],
                    }
                ]
            }
            self.analysis_call_count = 0
            self.generate_call_count = 0
            self.clarification_call_count = 0
            self.analysis_calls = []
            self.generation_calls = []
            self.clarification_calls = []

        def analyze_store_description(self, **kwargs):
            self.analysis_call_count += 1
            self.analysis_calls.append(deepcopy(kwargs))
            return AIAgenticGraphSkeletonTests._as_provider_response(
                self.analysis_payload
            )

        def generate_agentic_store_draft(self, **kwargs):
            self.generate_call_count += 1
            self.generation_calls.append(deepcopy(kwargs))
            return AIAgenticGraphSkeletonTests._as_provider_response(
                self.draft_payload
            )

        def generate_clarification_questions(self, **kwargs):
            self.clarification_call_count += 1
            self.clarification_calls.append(deepcopy(kwargs))
            return AIAgenticGraphSkeletonTests._as_provider_response(
                self.clarification_payload
            )

    @staticmethod
    def _question(
        question_key="primary_store_domain",
        question_text="What type of store should be created?",
        options=None,
    ):
        return {
            "question_key": question_key,
            "question_text": question_text,
            "options": options or ["Coffee", "Fashion"],
        }

    @staticmethod
    def _answer(question_key="primary_store_domain", selected_option="Coffee"):
        return {
            "question_key": question_key,
            "selected_option": selected_option,
        }

    @staticmethod
    def _sufficient_analysis_payload():
        return {
            "description_language": "en",
            "description_sufficient": True,
            "detected_store_domains": ["coffee"],
            "business_summary": "A coffee store for specialty products.",
            "target_audience": "",
            "product_direction": ["specialty coffee"],
            "blocking_missing_information": [],
            "ambiguities": [],
        }

    @staticmethod
    def _insufficient_analysis_payload(blocking_key="product_direction"):
        return {
            "description_language": "en",
            "description_sufficient": False,
            "detected_store_domains": ["coffee"],
            "business_summary": "The store domain is known, but a product direction is missing.",
            "target_audience": "",
            "product_direction": [],
            "blocking_missing_information": [blocking_key],
            "ambiguities": ["The product direction is not clear."],
        }

    def _prior_state(self, **overrides):
        questions = deepcopy(
            overrides.pop("clarification_questions", [self._question()])
        )
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "I want an online store",
            "normalized_description": "I want an online store",
            "available_theme_templates": ["Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "clarification",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "route_decision": "human_review",
            "description_sufficient": False,
            "clarification_questions": questions,
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": deepcopy(questions),
            },
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _run_resume_with_provider(self, prior_state, answers, provider):
        with patch(
            "AI_Store_Creation_Service.agentic.understanding.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.clarifying.get_ai_provider_client",
            return_value=provider,
        ), patch(
            "AI_Store_Creation_Service.agentic.generation.get_ai_provider_client",
            return_value=provider,
        ):
            return resume_agentic_workflow(
                prior_state=prior_state,
                clarification_answers=answers,
            )

    def _max_round_history_and_facts(self):
        history = []
        facts = {}
        for index in range(MAX_CLARIFICATION_ROUNDS):
            question_key = f"round_{index + 1}_decision"
            result = merging.merge_clarification_answers(
                clarification_questions=[
                    self._question(
                        question_key=question_key,
                        question_text=f"Question {index + 1}?",
                        options=["Coffee", "Fashion"],
                    )
                ],
                clarification_answers=[
                    self._answer(question_key=question_key, selected_option="Coffee")
                ],
                clarification_history=history,
                clarification_facts=facts,
                clarification_round_count=index,
            )
            history = result["clarification_history"]
            facts = result["clarification_facts"]
        return history, facts

    def test_resume_runner_sets_resume_entry_and_defensively_copies_inputs(self):
        ready_state = {
            "workflow_entry": "clarification_resume",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "I want an online store",
            "normalized_description": "I want an online store",
            "clarification_round_count": 1,
            "clarification_history": [
                {
                    "round_number": 1,
                    "questions": [self._question()],
                    "answers": [self._answer()],
                    "resolved_facts": {"primary_store_domain": "Coffee"},
                }
            ],
            "clarification_facts": {"primary_store_domain": "Coffee"},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "draft_ready",
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "route_decision": "human_review",
            "clarification_questions": [],
            "draft_payload": AIAgenticGraphSkeletonTests._valid_full_draft_payload(),
            "validation_errors": [],
        }
        fake_graph = AIAgenticRunnerTests.FakeCompiledGraph(ready_state)
        prior_state = self._prior_state()
        answers = [self._answer(selected_option=" coffee ")]
        prior_before = deepcopy(prior_state)
        answers_before = deepcopy(answers)

        with patch(
            "AI_Store_Creation_Service.agentic.runner.compile_agentic_graph",
            return_value=fake_graph,
        ):
            result = resume_agentic_workflow(
                prior_state=prior_state,
                clarification_answers=answers,
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(fake_graph.invoke_count, 1)
        self.assertEqual(
            fake_graph.received_state["workflow_entry"],
            "clarification_resume",
        )
        self.assertEqual(fake_graph.received_state["clarification_answers"], answers)
        self.assertIsNot(fake_graph.received_state["clarification_answers"], answers)
        self.assertEqual(prior_state, prior_before)
        self.assertEqual(answers, answers_before)

    def test_resume_becomes_sufficient_and_reaches_ready_for_review(self):
        provider = self.FakeResumeProvider(
            analysis_payload=self._sufficient_analysis_payload()
        )

        result = self._run_resume_with_provider(
            self._prior_state(),
            [self._answer(selected_option=" coffee ")],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(result["mode"], "draft_ready")
        self.assertEqual(result["clarification_round_count"], 1)
        self.assertEqual(result["clarification_facts"], {"primary_store_domain": "Coffee"})
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(provider.analysis_call_count, 1)
        self.assertEqual(provider.generate_call_count, 1)
        self.assertEqual(provider.clarification_call_count, 0)
        context = provider.analysis_calls[0]["clarification_context"]
        self.assertEqual(context["clarification_round_count"], 1)
        self.assertEqual(context["clarification_facts"], {"primary_store_domain": "Coffee"})
        self.assertEqual(context["clarification_history"][0]["round_number"], 1)

    def test_resume_still_insufficient_asks_only_unresolved_question(self):
        provider = self.FakeResumeProvider(
            analysis_payload=self._insufficient_analysis_payload("product_direction"),
            clarification_payload={
                "clarification_questions": [
                    {
                        "question_key": "product_direction",
                        "question_text": "What product direction should the store follow?",
                        "options": ["Beans", "Drinks"],
                    }
                ]
            },
        )

        result = self._run_resume_with_provider(
            self._prior_state(),
            [self._answer()],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["clarification_round_count"], 1)
        self.assertEqual(result["clarification_facts"], {"primary_store_domain": "Coffee"})
        self.assertEqual(
            result["clarification_questions"][0]["question_key"],
            "product_direction",
        )
        self.assertEqual(provider.analysis_call_count, 1)
        self.assertEqual(provider.clarification_call_count, 1)
        self.assertEqual(provider.generate_call_count, 0)

    def test_resolved_key_cannot_remain_blocking_after_resume(self):
        provider = self.FakeResumeProvider(
            analysis_payload=self._insufficient_analysis_payload(
                "primary_store_domain"
            )
        )

        result = self._run_resume_with_provider(
            self._prior_state(),
            [self._answer()],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(provider.analysis_call_count, 1)
        self.assertEqual(provider.clarification_call_count, 0)
        self.assertEqual(provider.generate_call_count, 0)

    def test_clarify_rejects_repeated_question_text_after_resume(self):
        provider = self.FakeResumeProvider(
            analysis_payload=self._insufficient_analysis_payload("product_direction"),
            clarification_payload={
                "clarification_questions": [
                    {
                        "question_key": "product_direction",
                        "question_text": "What type of store should be created?",
                        "options": ["Beans", "Drinks"],
                    }
                ]
            },
        )

        result = self._run_resume_with_provider(
            self._prior_state(),
            [self._answer()],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(provider.clarification_call_count, 1)
        self.assertEqual(provider.generate_call_count, 0)

    def test_max_rounds_after_merge_fail_without_clarify_or_generate(self):
        history, facts = self._max_round_history_and_facts()
        prior_state = self._prior_state(
            clarification_round_count=MAX_CLARIFICATION_ROUNDS - 1,
            clarification_history=history[:-1],
            clarification_facts={
                key: value
                for round_item in history[:-1]
                for key, value in round_item["resolved_facts"].items()
            },
            clarification_questions=[
                self._question(
                    "final_round_decision",
                    "What final direction should be used?",
                    ["Coffee", "Fashion"],
                )
            ],
            clarification_answers=[self._answer("final_round_decision", "Coffee")],
            draft_payload={
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": [
                    self._question(
                        "final_round_decision",
                        "What final direction should be used?",
                        ["Coffee", "Fashion"],
                    )
                ],
            },
        )
        provider = self.FakeResumeProvider(
            analysis_payload=self._insufficient_analysis_payload("product_direction")
        )

        result = self._run_resume_with_provider(
            prior_state,
            [self._answer("final_round_decision", "Coffee")],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["clarification_round_count"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(provider.analysis_call_count, 1)
        self.assertEqual(provider.clarification_call_count, 0)
        self.assertEqual(provider.generate_call_count, 0)

    def test_prior_count_at_max_fails_before_any_ai_call(self):
        history, facts = self._max_round_history_and_facts()
        provider = self.FakeResumeProvider(
            analysis_payload=self._sufficient_analysis_payload()
        )

        result = self._run_resume_with_provider(
            self._prior_state(
                clarification_round_count=MAX_CLARIFICATION_ROUNDS,
                clarification_history=history,
                clarification_facts=facts,
            ),
            [self._answer()],
            provider,
        )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(provider.analysis_call_count, 0)
        self.assertEqual(provider.clarification_call_count, 0)
        self.assertEqual(provider.generate_call_count, 0)

    def test_resume_runner_rejects_malformed_prior_state_safely(self):
        for prior_state in (
            "not-a-mapping",
            self._prior_state(status=WORKFLOW_STATUS_APPLIED),
            self._prior_state(draft_payload={}),
        ):
            with self.subTest(prior_state=prior_state):
                result = resume_agentic_workflow(
                    prior_state=prior_state,
                    clarification_answers=[self._answer()],
                )

                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                self.assertNotIn("Traceback", json.dumps(result))
                self.assertNotEqual(result.get("status"), WORKFLOW_STATUS_APPLIED)


class AIAgenticStateStoreTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def _ready_state(**overrides):
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "أريد متجر قهوة مختصة للعملاء الشباب",
            "normalized_description": "أريد متجر قهوة مختصة للعملاء الشباب",
            "available_theme_templates": ["Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "draft_ready",
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "route_decision": "human_review",
            "clarification_questions": [],
            "draft_payload": AIAgenticGraphSkeletonTests._valid_full_draft_payload(),
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def test_agentic_state_key_is_tenant_scoped_and_strict(self):
        key = build_ai_agentic_state_key(tenant_id=101, store_id=10)

        self.assertIn("agentic:v1", key)
        self.assertIn("tenant:101", key)
        self.assertIn("store:10", key)
        self.assertTrue(key.endswith(":state"))
        self.assertNotEqual(
            key,
            build_ai_agentic_state_key(tenant_id=102, store_id=10),
        )

        invalid_values = (True, False, 0, -1, "10", None, [], {})
        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build_ai_agentic_state_key(tenant_id=invalid, store_id=10)
                with self.assertRaises(ValueError):
                    build_ai_agentic_state_key(tenant_id=101, store_id=invalid)

        self.assertEqual(build_ai_draft_key(10), "ai_draft:store:10:draft")
        self.assertEqual(build_ai_draft_meta_key(10), "ai_draft:store:10:meta")

    def test_round_trip_uses_json_envelope_and_defensive_copies(self):
        state = self._ready_state()

        save_agentic_workflow_state(
            tenant_id=101,
            store_id=10,
            user_id=7,
            state=state,
        )
        key = build_ai_agentic_state_key(tenant_id=101, store_id=10)
        raw_value = cache.get(key)
        envelope = json.loads(raw_value)
        loaded = get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)

        self.assertIsInstance(raw_value, str)
        self.assertEqual(
            set(envelope),
            {"schema_version", "tenant_id", "store_id", "user_id", "state"},
        )
        self.assertEqual(envelope["schema_version"], AI_AGENTIC_STATE_SCHEMA_VERSION)
        self.assertEqual(loaded, state)
        self.assertIsNot(loaded, state)
        self.assertEqual(loaded["normalized_description"], "أريد متجر قهوة مختصة للعملاء الشباب")

        loaded["draft_payload"]["store"]["name"] = "Mutated"
        loaded_again = get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)
        self.assertNotEqual(loaded_again["draft_payload"]["store"]["name"], "Mutated")

    def test_save_rejects_malformed_state_and_identity_mismatch(self):
        invalid_states = (
            "not-mapping",
            self._ready_state(tenant_id=102),
            self._ready_state(store_id=11),
            self._ready_state(user_id=8),
            self._ready_state(non_serializable=object()),
            self._ready_state(score=float("nan")),
        )

        circular = self._ready_state()
        circular["loop"] = circular
        invalid_states = (*invalid_states, circular)

        for state in invalid_states:
            with self.subTest(state_type=type(state).__name__):
                with self.assertRaises(AgenticStateStoreError):
                    save_agentic_workflow_state(
                        tenant_id=101,
                        store_id=10,
                        user_id=7,
                        state=state,
                    )
        self.assertIsNone(
            get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)
        )

    def test_oversized_state_is_rejected_before_cache_set(self):
        oversized = self._ready_state(
            oversized_text="x" * (AI_AGENTIC_STATE_MAX_BYTES + 1)
        )

        with patch("AI_Store_Creation_Service.agentic_state_store.cache.set") as mock_set:
            with self.assertRaises(AgenticStateStoreError):
                save_agentic_workflow_state(
                    tenant_id=101,
                    store_id=10,
                    user_id=7,
                    state=oversized,
                )

        mock_set.assert_not_called()

    def test_get_malformed_envelope_returns_none_without_deleting(self):
        key = build_ai_agentic_state_key(tenant_id=101, store_id=10)
        malformed_values = (
            "not-json",
            json.dumps([]),
            json.dumps({"schema_version": 1}),
            json.dumps(
                {
                    "schema_version": 999,
                    "tenant_id": 101,
                    "store_id": 10,
                    "user_id": 7,
                    "state": self._ready_state(),
                }
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "tenant_id": 102,
                    "store_id": 10,
                    "user_id": 7,
                    "state": self._ready_state(),
                }
            ),
        )

        for raw_value in malformed_values:
            with self.subTest(raw_value=raw_value):
                cache.set(key, raw_value)
                self.assertIsNone(
                    get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)
                )
                self.assertIsNotNone(cache.get(key))

    @override_settings(AI_AGENTIC_STATE_CACHE_TTL=222)
    def test_ttl_resolution_prefers_explicit_then_agentic_then_draft_settings(self):
        state = self._ready_state()

        with patch("AI_Store_Creation_Service.agentic_state_store.cache.set") as mock_set:
            save_agentic_workflow_state(
                tenant_id=101,
                store_id=10,
                user_id=7,
                state=state,
                ttl_seconds=111,
            )
        self.assertEqual(mock_set.call_args.kwargs["timeout"], 111)

        with patch("AI_Store_Creation_Service.agentic_state_store.cache.set") as mock_set:
            save_agentic_workflow_state(
                tenant_id=101,
                store_id=10,
                user_id=7,
                state=state,
            )
        self.assertEqual(mock_set.call_args.kwargs["timeout"], 222)

        with override_settings(AI_AGENTIC_STATE_CACHE_TTL="bad", AI_DRAFT_CACHE_TTL=333):
            with patch("AI_Store_Creation_Service.agentic_state_store.cache.set") as mock_set:
                save_agentic_workflow_state(
                    tenant_id=101,
                    store_id=10,
                    user_id=7,
                    state=state,
                )
        self.assertEqual(mock_set.call_args.kwargs["timeout"], 333)

    def test_invalid_explicit_ttl_is_rejected(self):
        for ttl in ("60", True, 0, -1, None):
            if ttl is None:
                continue
            with self.subTest(ttl=ttl):
                with self.assertRaises(AgenticStateStoreError):
                    save_agentic_workflow_state(
                        tenant_id=101,
                        store_id=10,
                        user_id=7,
                        state=self._ready_state(),
                        ttl_seconds=ttl,
                    )

    def test_tenant_user_isolation_and_delete_do_not_touch_legacy_keys(self):
        save_ai_draft(10, {"legacy": "draft"})
        save_ai_draft_meta(10, {"legacy": "meta"})
        save_agentic_workflow_state(
            tenant_id=101,
            store_id=10,
            user_id=7,
            state=self._ready_state(),
        )

        self.assertIsNone(get_agentic_workflow_state(tenant_id=102, store_id=10, user_id=7))
        self.assertIsNone(get_agentic_workflow_state(tenant_id=101, store_id=11, user_id=7))
        self.assertIsNone(get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=8))
        self.assertFalse(delete_agentic_workflow_state(tenant_id=101, store_id=10, user_id=8))
        self.assertIsNotNone(get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7))

        self.assertTrue(delete_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7))
        self.assertIsNone(get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7))
        self.assertEqual(get_ai_draft(10), {"legacy": "draft"})
        self.assertEqual(get_ai_draft_meta(10), {"legacy": "meta"})

    def test_cache_backend_errors_fail_safely(self):
        with patch(
            "AI_Store_Creation_Service.agentic_state_store.cache.get",
            side_effect=RuntimeError("secret cache get 10.0.0.1"),
        ):
            self.assertIsNone(
                get_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)
            )

        with patch(
            "AI_Store_Creation_Service.agentic_state_store.cache.set",
            side_effect=RuntimeError("secret cache set 10.0.0.1"),
        ):
            with self.assertRaises(AgenticStateStoreError) as context:
                save_agentic_workflow_state(
                    tenant_id=101,
                    store_id=10,
                    user_id=7,
                    state=self._ready_state(),
                )
        self.assertNotIn("secret cache", str(context.exception))
        self.assertNotIn("10.0.0.1", str(context.exception))

        with patch(
            "AI_Store_Creation_Service.agentic_state_store.cache.delete",
            side_effect=RuntimeError("secret cache delete 10.0.0.1"),
        ):
            save_agentic_workflow_state(
                tenant_id=101,
                store_id=10,
                user_id=7,
                state=self._ready_state(),
            )
            self.assertFalse(
                delete_agentic_workflow_state(tenant_id=101, store_id=10, user_id=7)
            )

    def test_state_store_source_boundaries(self):
        source = inspect.getsource(agentic_state_store)
        for forbidden_reference in (
            "get_ai_provider_client",
            "compile_agentic_graph",
            "run_agentic_workflow",
            "resume_agentic_workflow",
            "models",
            "workflow_services",
            "requests",
            "redis",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, source)


class AIAgenticCachedSessionServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def _ready_state(**overrides):
        return AIAgenticStateStoreTests._ready_state(**overrides)

    @staticmethod
    def _failed_state(**overrides):
        state = build_safe_agentic_failure_state(
            store_id=10,
            tenant_id=101,
            user_id=7,
            user_store_description="I want an online store",
            normalized_description="I want an online store",
            clarification_round_count=0,
            repair_attempt_count=0,
        )
        state.update(overrides)
        return state

    @staticmethod
    def _question(question_key="primary_store_domain"):
        return {
            "question_key": question_key,
            "question_text": "What type of store should be created?",
            "options": ["Coffee", "Fashion"],
        }

    def _needs_state(self, **overrides):
        questions = deepcopy(overrides.pop("clarification_questions", [self._question()]))
        state = {
            "workflow_entry": "fresh",
            "store_id": 10,
            "tenant_id": 101,
            "user_id": 7,
            "user_store_description": "I want an online store",
            "normalized_description": "I want an online store",
            "available_theme_templates": ["Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "clarification",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "route_decision": "human_review",
            "description_sufficient": False,
            "clarification_questions": questions,
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": deepcopy(questions),
            },
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _save_prior(self, state):
        save_agentic_workflow_state(
            tenant_id=state["tenant_id"],
            store_id=state["store_id"],
            user_id=state["user_id"],
            state=state,
        )

    def test_resume_transition_classifier_requires_exact_count_increment(self):
        cases = (
            (0, self._ready_state(clarification_round_count=1), "overwrite"),
            (0, self._needs_state(clarification_round_count=1), "overwrite"),
            (0, self._ready_state(clarification_round_count=0), "malformed"),
            (1, self._needs_state(clarification_round_count=1), "malformed"),
            (1, self._failed_state(clarification_round_count=1), "do_not_overwrite"),
            (1, self._failed_state(clarification_round_count=2), "overwrite"),
            (1, self._ready_state(clarification_round_count=3), "malformed"),
            (2, self._ready_state(clarification_round_count=1), "malformed"),
            (1, self._ready_state(clarification_round_count=True), "malformed"),
            (1, self._ready_state(clarification_round_count="2"), "malformed"),
            (1, {**self._ready_state(), "status": "unknown_status"}, "malformed"),
        )

        for prior_count, result_state, expected in cases:
            with self.subTest(
                prior_count=prior_count,
                result_count=result_state.get("clarification_round_count"),
                status=result_state.get("status"),
            ):
                self.assertEqual(
                    agentic_session_services._classify_resume_transition(
                        prior_count=prior_count,
                        result_state=result_state,
                    ),
                    expected,
                )

        missing_count = self._ready_state()
        missing_count.pop("clarification_round_count")
        self.assertEqual(
            agentic_session_services._classify_resume_transition(
                prior_count=1,
                result_state=missing_count,
            ),
            "malformed",
        )

    def test_start_cached_workflow_saves_terminal_states_and_audits(self):
        for state in (
            self._needs_state(),
            self._ready_state(),
            self._failed_state(),
        ):
            cache.clear()
            with self.subTest(status=state["status"]), patch(
                "AI_Store_Creation_Service.agentic_session_services.run_agentic_workflow",
                return_value=deepcopy(state),
            ) as mock_run:
                result = start_cached_agentic_workflow(
                    store_id=10,
                    tenant_id=101,
                    user_id=7,
                    user_store_description="Very private full merchant description",
                    normalized_description="Very private full merchant description",
                    available_theme_templates=["Modern"],
                )

            mock_run.assert_called_once()
            self.assertEqual(result["status"], state["status"])
            self.assertEqual(
                get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7),
                result,
            )
            audit = AIStoreAuditLog.objects.filter(
                action="agentic_session_start",
                store_id=10,
            ).latest("id")
            self.assertIn("Terminal status=", audit.message)
            self.assertNotIn("Very private full merchant description", audit.message)
            self.assertNotIn("clarification_questions", audit.message)
            self.assertNotIn("draft_payload", audit.message)

    def test_start_save_failure_returns_safe_failure_without_raw_exception(self):
        with patch(
            "AI_Store_Creation_Service.agentic_session_services.run_agentic_workflow",
            return_value=self._ready_state(),
        ), patch(
            "AI_Store_Creation_Service.agentic_session_services.save_agentic_workflow_state",
            side_effect=RuntimeError("secret cache set 10.0.0.1"),
        ):
            result = start_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                user_store_description="Private description",
                normalized_description="Private description",
                available_theme_templates=["Modern"],
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        serialized = json.dumps(result)
        self.assertNotIn("secret cache", serialized)
        self.assertNotIn("10.0.0.1", serialized)
        audit = AIStoreAuditLog.objects.filter(action="agentic_session_start").latest("id")
        self.assertEqual(audit.status, "failed")
        self.assertNotIn("secret cache", audit.message)

    def test_resume_cache_miss_returns_failure_without_graph_call(self):
        with patch(
            "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow"
        ) as mock_resume:
            result = resume_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                clarification_answers=[
                    {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                ],
            )

        mock_resume.assert_not_called()
        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)

    def test_resume_success_to_ready_overwrites_cached_state(self):
        prior = self._needs_state()
        ready = self._ready_state(
            clarification_round_count=1,
            clarification_history=[
                {
                    "round_number": 1,
                    "questions": prior["clarification_questions"],
                    "answers": [
                        {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                    ],
                    "resolved_facts": {"primary_store_domain": "Coffee"},
                }
            ],
            clarification_facts={"primary_store_domain": "Coffee"},
        )
        self._save_prior(prior)

        with patch(
            "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
            return_value=ready,
        ) as mock_resume:
            result = resume_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                clarification_answers=[
                    {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                ],
            )

        mock_resume.assert_called_once()
        self.assertEqual(result["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
        self.assertEqual(cached["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(cached["clarification_round_count"], 1)
        self.assertEqual(cached["clarification_questions"], [])
        self.assertEqual(cached["clarification_facts"], {"primary_store_domain": "Coffee"})

    def test_resume_still_needs_clarification_overwrites_cached_state(self):
        prior = self._needs_state()
        next_questions = [
            {
                "question_key": "product_direction",
                "question_text": "What products should be sold?",
                "options": ["Beans", "Drinks"],
            }
        ]
        updated = self._needs_state(
            clarification_round_count=1,
            clarification_history=[
                {
                    "round_number": 1,
                    "questions": prior["clarification_questions"],
                    "answers": [
                        {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                    ],
                    "resolved_facts": {"primary_store_domain": "Coffee"},
                }
            ],
            clarification_facts={"primary_store_domain": "Coffee"},
            clarification_questions=next_questions,
            draft_payload={
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": next_questions,
            },
        )
        self._save_prior(prior)

        with patch(
            "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
            return_value=updated,
        ):
            result = resume_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                clarification_answers=[
                    {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                ],
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(result["clarification_round_count"], 1)
        cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
        self.assertEqual(cached["clarification_questions"], next_questions)

    def test_invalid_answers_failure_does_not_destroy_prior_session(self):
        prior = self._needs_state()
        failed = self._failed_state(clarification_round_count=0)
        self._save_prior(prior)

        with patch(
            "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
            return_value=failed,
        ):
            result = resume_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                clarification_answers=[{"question_key": "primary_store_domain", "selected_option": "Other"}],
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
        self.assertEqual(cached["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(cached["clarification_questions"], prior["clarification_questions"])

    def test_successful_resume_with_same_count_is_rejected_and_preserves_prior_cache(self):
        prior = self._needs_state()
        same_count_results = (
            self._ready_state(clarification_round_count=0),
            self._needs_state(clarification_round_count=0),
        )

        for same_count_result in same_count_results:
            cache.clear()
            self._save_prior(prior)
            with self.subTest(status=same_count_result["status"]), patch(
                "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
                return_value=same_count_result,
            ) as mock_resume, patch(
                "AI_Store_Creation_Service.agentic_session_services.save_agentic_workflow_state"
            ) as mock_save:
                result = resume_cached_agentic_workflow(
                    store_id=10,
                    tenant_id=101,
                    user_id=7,
                    clarification_answers=[
                        {
                            "question_key": "primary_store_domain",
                            "selected_option": "Coffee",
                        }
                    ],
                )

            mock_resume.assert_called_once()
            mock_save.assert_not_called()
            self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
            serialized = json.dumps(result)
            self.assertNotIn("Traceback", serialized)
            cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
            self.assertEqual(cached["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
            self.assertEqual(cached["clarification_round_count"], 0)
            self.assertEqual(
                cached["clarification_questions"],
                prior["clarification_questions"],
            )

    def test_consumed_round_failure_overwrites_prior_state(self):
        prior = self._needs_state(clarification_round_count=2)
        failed = self._failed_state(clarification_round_count=3)
        self._save_prior(prior)

        with patch(
            "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
            return_value=failed,
        ):
            result = resume_cached_agentic_workflow(
                store_id=10,
                tenant_id=101,
                user_id=7,
                clarification_answers=[
                    {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                ],
            )

        self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
        self.assertEqual(cached["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(cached["clarification_round_count"], 3)

    def test_malformed_counter_transition_does_not_overwrite_prior(self):
        prior = self._needs_state(clarification_round_count=1)
        self._save_prior(prior)
        malformed_results = (
            self._ready_state(clarification_round_count=0),
            self._ready_state(clarification_round_count=3),
            self._ready_state(clarification_round_count=True),
            self._ready_state(clarification_round_count="2"),
            self._ready_state(clarification_round_count=MAX_CLARIFICATION_ROUNDS + 1),
        )

        for malformed in malformed_results:
            with self.subTest(count=malformed["clarification_round_count"]):
                with patch(
                    "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow",
                    return_value=malformed,
                ):
                    result = resume_cached_agentic_workflow(
                        store_id=10,
                        tenant_id=101,
                        user_id=7,
                        clarification_answers=[
                            {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                        ],
                    )

                self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
                cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
                self.assertEqual(cached["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
                self.assertEqual(cached["clarification_round_count"], 1)

    def test_ready_or_failed_cached_state_cannot_resume(self):
        for prior in (self._ready_state(), self._failed_state()):
            cache.clear()
            self._save_prior(prior)
            with self.subTest(status=prior["status"]), patch(
                "AI_Store_Creation_Service.agentic_session_services.resume_agentic_workflow"
            ) as mock_resume:
                result = resume_cached_agentic_workflow(
                    store_id=10,
                    tenant_id=101,
                    user_id=7,
                    clarification_answers=[
                        {"question_key": "primary_store_domain", "selected_option": "Coffee"}
                    ],
                )

            mock_resume.assert_not_called()
            self.assertEqual(result["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
            cached = get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7)
            self.assertEqual(cached["status"], prior["status"])

    def test_delete_cached_workflow_validates_identity(self):
        self._save_prior(self._needs_state())

        self.assertFalse(delete_cached_agentic_workflow(store_id=10, tenant_id=102, user_id=7))
        self.assertFalse(delete_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=8))
        self.assertIsNotNone(get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7))
        self.assertTrue(delete_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7))
        self.assertIsNone(get_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7))
        self.assertFalse(delete_cached_agentic_workflow(store_id=10, tenant_id=101, user_id=7))

    def test_session_source_boundaries_and_runner_remains_cache_free(self):
        session_source = inspect.getsource(agentic_session_services)
        state_store_source = inspect.getsource(agentic_state_store)
        runner_source = inspect.getsource(runner)
        graph_source = inspect.getsource(importlib.import_module("AI_Store_Creation_Service.agentic.graph"))

        self.assertNotIn("django.core.cache", session_source)
        self.assertNotIn("cache.", session_source)
        self.assertNotIn("get_ai_provider_client", session_source)
        self.assertNotIn("Ollama", session_source)
        self.assertNotIn("Store.objects", session_source)
        self.assertNotIn("apply_current_ai_draft", session_source)

        self.assertIn("django.core.cache", state_store_source)
        self.assertNotIn("compile_agentic_graph", state_store_source)
        self.assertNotIn("get_ai_provider_client", state_store_source)

        self.assertNotIn("django.core.cache", runner_source)
        self.assertNotIn("agentic_state_store", runner_source)
        self.assertNotIn("audit_services", runner_source)
        self.assertNotIn("django.core.cache", graph_source)


class AIAgenticProductionBridgeTests(TestCase):
    def setUp(self):
        cache.clear()
        ThemeTemplate.objects.all().delete()
        self.user = User.objects.create_user(
            username="agentic_bridge_owner",
            email="agentic_bridge_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    def tearDown(self):
        cache.clear()

    def _create_store(self, *, owner=None, tenant_id=None) -> Store:
        owner = owner or self.user
        return Store.objects.create(
            owner=owner,
            tenant_id=tenant_id or owner.tenant_id,
            name="Agentic Draft Store",
            description="",
            status="draft",
        )

    def _ready_state(self, store: Store, **overrides):
        state = AIAgenticStateStoreTests._ready_state(
            store_id=store.id,
            tenant_id=store.tenant_id,
            user_id=store.owner_id,
            user_store_description="Create a modern skincare store for young women",
            normalized_description="Create a modern skincare store for young women",
            available_theme_templates=["Classic", "Modern"],
        )
        state.update(overrides)
        return state

    def _needs_state(self, store: Store, **overrides):
        questions = overrides.pop(
            "clarification_questions",
            [
                {
                    "question_key": "primary_store_domain",
                    "question_text": "What type of store should be created?",
                    "options": ["Coffee", "Fashion"],
                }
            ],
        )
        state = {
            "workflow_entry": "fresh",
            "store_id": store.id,
            "tenant_id": store.tenant_id,
            "user_id": store.owner_id,
            "user_store_description": "I want a modern online store for customers",
            "normalized_description": "I want a modern online store for customers",
            "available_theme_templates": ["Classic", "Modern"],
            "clarification_round_count": 0,
            "clarification_history": [],
            "clarification_facts": {},
            "repair_attempt_count": 0,
            "current_step": "human_review",
            "mode": "clarification",
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "route_decision": "human_review",
            "clarification_questions": deepcopy(questions),
            "draft_payload": {
                "store": {},
                "store_settings": {},
                "theme": {},
                "categories": [],
                "products": [],
                "clarification_needed": True,
                "clarification_questions": deepcopy(questions),
            },
            "validation_errors": [],
        }
        state.update(overrides)
        return state

    def _failed_state(self, store: Store, **overrides):
        state = build_safe_agentic_failure_state(
            store_id=store.id,
            tenant_id=store.tenant_id,
            user_id=store.owner_id,
            user_store_description="Create a modern skincare store for young women",
            normalized_description="Create a modern skincare store for young women",
        )
        state.update(overrides)
        return state

    def _save_agentic_state(self, state):
        save_agentic_workflow_state(
            tenant_id=state["tenant_id"],
            store_id=state["store_id"],
            user_id=state["user_id"],
            state=state,
        )

    def test_start_bridge_creates_draft_store_and_projects_ready_state(self):
        def fake_start(**kwargs):
            store = Store.objects.get(id=kwargs["store_id"])
            return self._ready_state(
                store,
                user_store_description=kwargs["user_store_description"],
                normalized_description=kwargs["normalized_description"],
                available_theme_templates=kwargs["available_theme_templates"],
            )

        initial_store_count = Store.objects.count()
        with patch(
            "AI_Store_Creation_Service.agentic_production_services.start_cached_agentic_workflow",
            side_effect=fake_start,
        ) as mock_start:
            result = agentic_production_services.start_agentic_ai_draft_workflow(
                user=self.user,
                tenant_id=101,
                user_store_description="  Create   a modern skincare store for young women. ",
            )

        self.assertEqual(Store.objects.count(), initial_store_count + 1)
        created_store = Store.objects.get(id=result["store_id"])
        self.assertEqual(created_store.owner_id, self.user.id)
        self.assertEqual(created_store.tenant_id, 101)
        self.assertEqual(created_store.status, "draft")
        self.assertEqual(
            created_store.description,
            "Create a modern skincare store for young women.",
        )
        mock_start.assert_called_once()
        self.assertEqual(
            mock_start.call_args.kwargs["normalized_description"],
            "Create a modern skincare store for young women.",
        )
        self.assertEqual(
            mock_start.call_args.kwargs["available_theme_templates"],
            ["Classic", "Modern"],
        )
        self.assertEqual(set(result), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(result["draft_metadata"]["workflow_engine"], "agentic")
        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertNotIn("tenant_id", result)
        self.assertNotIn("user_id", json.dumps(result))

    def test_invalid_description_fails_before_store_or_agentic_session_creation(self):
        initial_store_count = Store.objects.count()
        with patch(
            "AI_Store_Creation_Service.agentic_production_services.start_cached_agentic_workflow"
        ) as mock_start:
            with self.assertRaises(ValidationError):
                agentic_production_services.start_agentic_ai_draft_workflow(
                    user=self.user,
                    tenant_id=101,
                    user_store_description="Too short",
                )

        mock_start.assert_not_called()
        self.assertEqual(Store.objects.count(), initial_store_count)

    def test_failed_recoverable_state_projects_safe_failure_contract(self):
        store = self._create_store()
        state = self._failed_state(store)

        result = agentic_production_services._project_agentic_state_to_public_response(state)

        self.assertEqual(set(result), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(result["draft_metadata"]["is_fallback"])
        self.assertFalse(result["draft_payload"]["clarification_needed"])
        self.assertEqual(result["draft_payload"]["clarification_questions"], [])
        serialized = json.dumps(result)
        self.assertNotIn("Traceback", serialized)
        self.assertNotIn("provider_response", serialized)

    def test_get_current_agentic_draft_uses_authorized_session_and_hides_internal_state(self):
        store = self._create_store()
        state = self._ready_state(
            store,
            understanding_reasons=["internal reason"],
            route_decision="human_review",
            clarification_facts={"primary_store_domain": "Coffee"},
        )
        self._save_agentic_state(state)

        result = agentic_production_services.get_current_agentic_ai_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )
        result["draft_payload"]["store"]["name"] = "Mutated"
        fresh_result = agentic_production_services.get_current_agentic_ai_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )

        self.assertEqual(set(result), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(result["draft_metadata"]["workflow_engine"], "agentic")
        serialized = json.dumps(result)
        for hidden_key in (
            "tenant_id",
            "user_id",
            "workflow_entry",
            "understanding_reasons",
            "route_decision",
            "clarification_facts",
            "clarification_answers",
            "provider_response",
        ):
            with self.subTest(hidden_key=hidden_key):
                self.assertNotIn(hidden_key, serialized)
        self.assertNotEqual(fresh_result["draft_payload"]["store"]["name"], "Mutated")

    def test_process_agentic_clarification_returns_draft_payload_only(self):
        store = self._create_store()
        self._save_agentic_state(self._needs_state(store))
        ready = self._ready_state(store, clarification_round_count=1)

        with patch(
            "AI_Store_Creation_Service.agentic_production_services.resume_cached_agentic_workflow",
            return_value=ready,
        ) as mock_resume:
            result = agentic_production_services.process_agentic_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers=[
                    {
                        "question_key": "primary_store_domain",
                        "selected_option": "Coffee",
                    }
                ],
            )

        mock_resume.assert_called_once()
        self.assertIn("store", result)
        self.assertIn("clarification_needed", result)
        self.assertNotIn("draft_metadata", result)
        self.assertNotIn("workflow_engine", result)
        self.assertFalse(result["clarification_needed"])

    def test_agentic_session_detection_enforces_authorization_before_session_lookup(self):
        store = self._create_store()
        self._save_agentic_state(self._ready_state(store))
        other_user = User.objects.create_user(
            username="other_agentic_user",
            email="other_agentic_user@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        other_user.is_active = True
        other_user.tenant_id = 101
        other_user.save(update_fields=["is_active", "tenant_id"])
        invalid_attempts = (
            {"user": self.user, "tenant_id": 102},
            {"user": other_user, "tenant_id": 101},
            {"user": AnonymousUser(), "tenant_id": 101},
            {"user": self.user, "tenant_id": None},
        )

        for attempt in invalid_attempts:
            with self.subTest(attempt=attempt), patch(
                "AI_Store_Creation_Service.agentic_production_services.get_cached_agentic_workflow"
            ) as mock_get_cached:
                with self.assertRaises(ValidationError):
                    agentic_production_services.get_existing_agentic_session(
                        store_id=store.id,
                        user=attempt["user"],
                        tenant_id=attempt["tenant_id"],
                    )
                mock_get_cached.assert_not_called()

    def test_store_selector_fails_closed_for_malformed_identities(self):
        store = self._create_store()

        self.assertEqual(get_store_for_ai_flow(store.id, self.user, 101), store)
        for invalid_store_id in (True, False, "1", None, 0, -1):
            with self.subTest(invalid_store_id=invalid_store_id):
                self.assertIsNone(
                    get_store_for_ai_flow(invalid_store_id, self.user, 101)
                )
        for invalid_tenant_id in (True, False, "101", None, 0, -1):
            with self.subTest(invalid_tenant_id=invalid_tenant_id):
                self.assertIsNone(
                    get_store_for_ai_flow(store.id, self.user, invalid_tenant_id)
                )

    def test_agentic_production_bridge_source_boundaries(self):
        source = inspect.getsource(agentic_production_services)
        for forbidden_reference in (
            "compile_agentic_graph",
            "run_agentic_workflow",
            "resume_agentic_workflow",
            "get_ai_provider_client",
            "django.core.cache",
            "cache.get",
            "cache.set",
            "save_ai_draft",
            "save_ai_draft_meta",
            "APIView",
            "serializer",
        ):
            with self.subTest(forbidden_reference=forbidden_reference):
                self.assertNotIn(forbidden_reference, source)


class AIFeatureFlagProductionRoutingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="flag_routing_owner",
            email="flag_routing_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

    def tearDown(self):
        cache.clear()

    def _create_store(self) -> Store:
        return Store.objects.create(
            owner=self.user,
            tenant_id=101,
            name="Routing Store",
            description="",
            status="draft",
        )

    def _ready_state(self, store: Store, **overrides):
        state = AIAgenticStateStoreTests._ready_state(
            store_id=store.id,
            tenant_id=store.tenant_id,
            user_id=store.owner_id,
            user_store_description="Create a modern skincare store for young women",
            normalized_description="Create a modern skincare store for young women",
        )
        state.update(overrides)
        return state

    def _needs_state(self, store: Store, **overrides):
        return AIAgenticProductionBridgeTests._needs_state(self, store, **overrides)

    def _save_agentic_state(self, state):
        save_agentic_workflow_state(
            tenant_id=state["tenant_id"],
            store_id=state["store_id"],
            user_id=state["user_id"],
            state=state,
        )

    def _protected_operation_cases(self, store: Store, *, user=None, tenant_id=101):
        user = user or self.user
        return (
            (
                services.generate_initial_store_draft,
                {
                    "store_id": store.id,
                    "user": user,
                    "tenant_id": tenant_id,
                    "user_store_description": "Create a modern skincare store for young women",
                },
                "AI_Store_Creation_Service.workflow_services.generate_initial_store_draft",
            ),
            (
                services.regenerate_store_draft,
                {"store_id": store.id, "user": user, "tenant_id": tenant_id},
                "AI_Store_Creation_Service.workflow_services.regenerate_store_draft",
            ),
            (
                services.regenerate_store_draft_section,
                {
                    "store_id": store.id,
                    "user": user,
                    "tenant_id": tenant_id,
                    "target_section": "theme",
                },
                "AI_Store_Creation_Service.workflow_services.regenerate_store_draft_section",
            ),
            (
                services.apply_current_ai_draft_store_core,
                {"store_id": store.id, "user": user, "tenant_id": tenant_id},
                "AI_Store_Creation_Service.apply_services.apply_current_ai_draft_store_core",
            ),
            (
                services.apply_current_ai_draft_categories,
                {"store_id": store.id, "user": user, "tenant_id": tenant_id},
                "AI_Store_Creation_Service.apply_services.apply_current_ai_draft_categories",
            ),
            (
                services.apply_current_ai_draft_products,
                {"store_id": store.id, "user": user, "tenant_id": tenant_id},
                "AI_Store_Creation_Service.apply_services.apply_current_ai_draft_products",
            ),
            (
                services.apply_current_ai_draft_to_store,
                {"store_id": store.id, "user": user, "tenant_id": tenant_id},
                "AI_Store_Creation_Service.apply_services.apply_current_ai_draft_to_store",
            ),
        )

    def test_feature_flag_accepts_only_explicit_boolean_true(self):
        with patch.object(feature_flags, "settings", object()):
            self.assertFalse(is_agentic_workflow_enabled())

        cases = (
            (False, False),
            (True, True),
            ("true", False),
            ("false", False),
            ("1", False),
            (1, False),
            (0, False),
            (None, False),
            ([], False),
            ({}, False),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                with override_settings(AI_AGENTIC_WORKFLOW_ENABLED=value):
                    self.assertIs(is_agentic_workflow_enabled(), expected)

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=False)
    def test_flag_off_start_uses_legacy_and_does_not_start_agentic_session(self):
        legacy_response = {
            "store_id": 99,
            "draft_payload": {"legacy": True},
            "draft_metadata": {"workflow_engine": "legacy"},
        }
        with patch(
            "AI_Store_Creation_Service.workflow_services.start_ai_draft_workflow",
            return_value=legacy_response,
        ) as mock_legacy_start, patch(
            "AI_Store_Creation_Service.agentic_production_services.start_agentic_ai_draft_workflow"
        ) as mock_agentic_start, patch(
            "AI_Store_Creation_Service.agentic_state_store.save_agentic_workflow_state"
        ) as mock_agentic_save:
            result = services.start_ai_draft_workflow(
                user=self.user,
                tenant_id=101,
                user_store_description="Create a modern skincare store for young women",
            )

        self.assertEqual(result, legacy_response)
        mock_legacy_start.assert_called_once()
        mock_agentic_start.assert_not_called()
        mock_agentic_save.assert_not_called()

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=True)
    def test_flag_on_start_uses_agentic_and_does_not_call_legacy_start(self):
        agentic_response = {
            "store_id": 10,
            "draft_payload": {"clarification_needed": False},
            "draft_metadata": {"workflow_engine": "agentic"},
        }
        with patch(
            "AI_Store_Creation_Service.agentic_production_services.start_agentic_ai_draft_workflow",
            return_value=agentic_response,
        ) as mock_agentic_start, patch(
            "AI_Store_Creation_Service.workflow_services.start_ai_draft_workflow"
        ) as mock_legacy_start:
            result = services.start_ai_draft_workflow(
                user=self.user,
                tenant_id=101,
                user_store_description="Create a modern skincare store for young women",
            )

        self.assertEqual(result, agentic_response)
        mock_agentic_start.assert_called_once()
        mock_legacy_start.assert_not_called()

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=True)
    def test_agentic_failure_start_does_not_fall_back_to_legacy(self):
        def failed_start(**kwargs):
            return build_safe_agentic_failure_state(
                store_id=kwargs["store_id"],
                tenant_id=kwargs["tenant_id"],
                user_id=kwargs["user_id"],
                user_store_description=kwargs["user_store_description"],
                normalized_description=kwargs["normalized_description"],
            )

        with patch(
            "AI_Store_Creation_Service.agentic_production_services.start_cached_agentic_workflow",
            side_effect=failed_start,
        ) as mock_agentic_start, patch(
            "AI_Store_Creation_Service.workflow_services.start_ai_draft_workflow"
        ) as mock_legacy_start, patch(
            "AI_Store_Creation_Service.services.get_ai_provider_client"
        ) as mock_provider:
            result = services.start_ai_draft_workflow(
                user=self.user,
                tenant_id=101,
                user_store_description="Create a modern skincare store for young women",
            )

        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["draft_metadata"]["workflow_engine"], "agentic")
        mock_agentic_start.assert_called_once()
        mock_legacy_start.assert_not_called()
        mock_provider.assert_not_called()

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=False)
    def test_existing_agentic_session_get_and_clarification_continue_after_flag_off(self):
        store = self._create_store()
        self._save_agentic_state(self._needs_state(store))
        ready = self._ready_state(store, clarification_round_count=1)

        with patch(
            "AI_Store_Creation_Service.workflow_services.get_current_ai_draft"
        ) as mock_legacy_get:
            current = services.get_current_ai_draft(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )
        self.assertEqual(current["draft_metadata"]["workflow_engine"], "agentic")
        mock_legacy_get.assert_not_called()

        with patch(
            "AI_Store_Creation_Service.agentic_production_services.resume_cached_agentic_workflow",
            return_value=ready,
        ) as mock_resume, patch(
            "AI_Store_Creation_Service.workflow_services.process_clarification_round"
        ) as mock_legacy_clarification:
            payload = services.process_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers=[
                    {
                        "question_key": "primary_store_domain",
                        "selected_option": "Coffee",
                    }
                ],
            )

        mock_resume.assert_called_once()
        mock_legacy_clarification.assert_not_called()
        self.assertFalse(payload["clarification_needed"])

    @override_settings(AI_AGENTIC_WORKFLOW_ENABLED=True)
    def test_existing_legacy_session_continues_under_flag_on_without_migration(self):
        store = self._create_store()
        legacy_payload = {"legacy": True, "clarification_needed": True}
        save_ai_draft(store.id, legacy_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 0,
                "original_user_store_description": "Create a legacy store for testing",
            },
        )

        with patch(
            "AI_Store_Creation_Service.workflow_services.get_current_ai_draft",
            return_value={
                "store_id": store.id,
                "draft_payload": legacy_payload,
                "draft_metadata": {"workflow_engine": "legacy"},
            },
        ) as mock_legacy_get, patch(
            "AI_Store_Creation_Service.agentic_production_services.resume_cached_agentic_workflow"
        ) as mock_agentic_resume:
            result = services.get_current_ai_draft(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
            )

        self.assertEqual(result["draft_metadata"]["workflow_engine"], "legacy")
        mock_legacy_get.assert_called_once()
        mock_agentic_resume.assert_not_called()
        self.assertIsNone(
            get_cached_agentic_workflow(
                store_id=store.id,
                tenant_id=101,
                user_id=self.user.id,
            )
        )

    def test_when_both_session_types_exist_agentic_has_priority_and_legacy_is_untouched(self):
        store = self._create_store()
        legacy_payload = {"legacy": "draft"}
        legacy_meta = {"legacy": "meta"}
        save_ai_draft(store.id, legacy_payload)
        save_ai_draft_meta(store.id, legacy_meta)
        self._save_agentic_state(self._needs_state(store))
        ready = self._ready_state(store, clarification_round_count=1)

        current = services.get_current_ai_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
        )
        self.assertEqual(current["draft_metadata"]["workflow_engine"], "agentic")

        with patch(
            "AI_Store_Creation_Service.agentic_production_services.resume_cached_agentic_workflow",
            return_value=ready,
        ):
            services.process_clarification_round(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                clarification_answers=[
                    {
                        "question_key": "primary_store_domain",
                        "selected_option": "Coffee",
                    }
                ],
            )

        self.assertEqual(get_ai_draft(store.id), legacy_payload)
        self.assertEqual(get_ai_draft_meta(store.id), legacy_meta)
        self.assertEqual(
            get_cached_agentic_workflow(
                store_id=store.id,
                tenant_id=101,
                user_id=self.user.id,
            )["status"],
            WORKFLOW_STATUS_NEEDS_CLARIFICATION,
        )

    def test_unsupported_agentic_operations_raise_safe_validation_error(self):
        store = self._create_store()
        self._save_agentic_state(self._ready_state(store))

        for function, kwargs, patch_target in self._protected_operation_cases(store):
            with self.subTest(function=function.__name__), patch(
                patch_target
            ) as mocked_legacy, patch(
                "AI_Store_Creation_Service.services.get_ai_provider_client"
            ) as mock_provider:
                with self.assertRaises(ValidationError) as context:
                    function(**kwargs)
                self.assertIn(
                    AGENTIC_OPERATION_NOT_AVAILABLE_USER_MESSAGE,
                    str(context.exception),
                )
                mocked_legacy.assert_not_called()
                mock_provider.assert_not_called()
        self.assertIsNotNone(
            get_cached_agentic_workflow(
                store_id=store.id,
                tenant_id=101,
                user_id=self.user.id,
            )
        )

    def test_protected_operations_do_not_fallback_to_legacy_on_authorization_failure(self):
        store = self._create_store()
        self._save_agentic_state(self._ready_state(store))
        other_user = User.objects.create_user(
            username="flag_routing_other",
            email="flag_routing_other@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        other_user.is_active = True
        other_user.tenant_id = 101
        other_user.save(update_fields=["is_active", "tenant_id"])
        unauthorized_contexts = (
            ("user_mismatch", store.id, other_user, 101),
            ("tenant_mismatch", store.id, self.user, 102),
            ("anonymous_user", store.id, AnonymousUser(), 101),
            ("missing_tenant", store.id, self.user, None),
            ("zero_store_id", 0, self.user, 101),
            ("boolean_store_id", True, self.user, 101),
            ("missing_store", store.id + 999999, self.user, 101),
        )
        original_state = get_cached_agentic_workflow(
            store_id=store.id,
            tenant_id=101,
            user_id=self.user.id,
        )

        for label, store_id, user, tenant_id in unauthorized_contexts:
            operation_store = Store(id=store_id, owner=self.user, tenant_id=101)
            for function, kwargs, patch_target in self._protected_operation_cases(
                operation_store,
                user=user,
                tenant_id=tenant_id,
            ):
                kwargs["store_id"] = store_id
                with self.subTest(label=label, function=function.__name__), patch(
                    patch_target
                ) as mocked_legacy, patch(
                    "AI_Store_Creation_Service.services.get_ai_provider_client"
                ) as mock_provider:
                    with self.assertRaises(ValidationError):
                        function(**kwargs)

                    mocked_legacy.assert_not_called()
                    mock_provider.assert_not_called()

        self.assertEqual(
            get_cached_agentic_workflow(
                store_id=store.id,
                tenant_id=101,
                user_id=self.user.id,
            ),
            original_state,
        )

    def test_agentic_guard_source_does_not_swallow_validation_error(self):
        source = inspect.getsource(services._raise_if_agentic_session_exists)

        self.assertIn("has_existing_agentic_session", source)
        self.assertNotIn("except ValidationError", source)
        self.assertNotIn("except Exception", source)

    def test_legacy_operations_still_delegate_when_no_agentic_session_exists(self):
        store = self._create_store()

        for function, kwargs, patch_target in self._protected_operation_cases(store):
            with self.subTest(function=function.__name__), patch(
                patch_target,
                return_value={"legacy": function.__name__},
            ) as mocked_legacy:
                result = function(**kwargs)

            self.assertEqual(result, {"legacy": function.__name__})
            mocked_legacy.assert_called_once()


class AIProviderSelectionTests(TestCase):
    def test_provider_contract_requires_agentic_generation_method(self):
        self.assertIn(
            "generate_agentic_store_draft",
            AIProviderContract.__abstractmethods__,
        )

    @override_settings(AI_PROVIDER="ollama", AI_API_KEY="test-ollama-key")
    def test_factory_returns_ollama_provider(self):
        provider = get_ai_provider_client()
        self.assertIsInstance(provider, OllamaProviderClient)

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="test-ollama-key",
        AI_API_URL="https://ollama.example/api/chat",
        AI_MODEL_NAME="test-ollama-model",
        AI_TIMEOUT=17,
        AI_TEMPERATURE=0.35,
    )
    @patch("AI_Store_Creation_Service.providers._post_json_request")
    def test_ollama_request_headers_and_body_contract(self, mock_post_json_request):
        mock_post_json_request.return_value = {
            "message": {"content": '{"ok": true}'}
        }
        provider = OllamaProviderClient()

        provider.generate_store_draft(
            tenant_id=101,
            store_id=77,
            user_store_description="Build a modern beauty store",
            available_theme_templates=["Modern", "Classic"],
        )

        call_kwargs = mock_post_json_request.call_args.kwargs
        headers = call_kwargs["headers"]
        payload = call_kwargs["payload"]

        self.assertEqual(call_kwargs["url"], "https://ollama.example/api/chat")
        self.assertEqual(call_kwargs["timeout"], 17)
        self.assertEqual(headers["Authorization"], "Bearer test-ollama-key")
        self.assertEqual(headers["Content-Type"], "application/json")

        self.assertEqual(payload["model"], "test-ollama-model")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["temperature"], 0.35)
        self.assertIsInstance(payload["messages"], list)
        self.assertTrue(payload["messages"])

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="test-ollama-key",
        AI_MODEL_NAME="configured-ollama-model",
        AI_TIMEOUT=23,
        AI_TEMPERATURE=0.1,
    )
    def test_ollama_uses_configured_model_timeout_and_temperature(self):
        provider = OllamaProviderClient()
        payload = provider._build_chat_payload(
            [
                {"role": "user", "content": "Hello"},
            ]
        )

        self.assertEqual(provider.model_name, "configured-ollama-model")
        self.assertEqual(provider.timeout, 23)
        self.assertEqual(provider.temperature, 0.1)
        self.assertEqual(payload["model"], "configured-ollama-model")
        self.assertEqual(payload["options"]["temperature"], 0.1)

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="test-ollama-key",
        AI_API_URL="https://ollama.example/api/chat",
        AI_MODEL_NAME="analysis-model",
        AI_TIMEOUT=19,
        AI_TEMPERATURE=0.15,
    )
    @patch("AI_Store_Creation_Service.providers._post_json_request")
    def test_ollama_analyze_store_description_uses_prompt_builder_and_transport(
        self,
        mock_post_json_request,
    ):
        mock_post_json_request.return_value = {
            "message": {"content": '{"description_sufficient": true}'}
        }
        provider = OllamaProviderClient()

        provider.analyze_store_description(
            tenant_id=101,
            store_id=77,
            normalized_description="Coffee shop",
        )

        call_kwargs = mock_post_json_request.call_args.kwargs
        payload = call_kwargs["payload"]
        messages = payload["messages"]

        self.assertEqual(call_kwargs["url"], "https://ollama.example/api/chat")
        self.assertEqual(call_kwargs["timeout"], 19)
        self.assertEqual(payload["model"], "analysis-model")
        self.assertEqual(payload["options"]["temperature"], 0.15)
        self.assertIn("semantic analysis only", messages[0]["content"])
        self.assertIn("tenant_id: 101", messages[1]["content"])
        self.assertIn("store_id: 77", messages[2]["content"])
        self.assertIn("normalized_description: Coffee shop", messages[3]["content"])

    def test_analyze_store_description_prompt_contract(self):
        messages = build_analyze_store_description_messages(
            tenant_id=101,
            store_id=77,
            normalized_description="Coffee shop",
        )
        system_prompt = messages[0]["content"].lower()

        for expected_text in (
            "semantic analysis only",
            "do not generate a store draft",
            "do not generate clarification questions",
            "do not write question text",
            "clarify node is responsible for generating questions later",
            "do not choose or return route_decision",
            "return exactly one json object only",
            "return these exact top-level keys",
            "short descriptions may still be sufficient",
            "long descriptions may still be insufficient",
            "do not force clarification for optional details",
        ):
            with self.subTest(expected_text=expected_text):
                self.assertIn(expected_text, system_prompt)

        self.assertNotIn('"store": {', system_prompt)
        self.assertNotIn('"products": [', system_prompt)
        self.assertNotIn('"clarification_questions": [', system_prompt)

    def test_analyze_store_description_example_uses_true_blocking_business_decision(self):
        messages = build_analyze_store_description_messages(
            tenant_id=101,
            store_id=77,
            normalized_description="Fashion and electronics store",
        )
        system_prompt = messages[0]["content"]

        self.assertIn('"blocking_missing_information": ["primary_store_domain"]', system_prompt)
        self.assertIn('"detected_store_domains": ["fashion", "electronics"]', system_prompt)
        self.assertNotIn('"blocking_missing_information": ["target_audience"]', system_prompt)

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="test-ollama-key",
        AI_API_URL="https://ollama.example/api/chat",
        AI_MODEL_NAME="clarify-model",
        AI_TIMEOUT=21,
        AI_TEMPERATURE=0.2,
    )
    @patch("AI_Store_Creation_Service.providers._post_json_request")
    def test_ollama_generate_clarification_questions_uses_prompt_builder_and_transport(
        self,
        mock_post_json_request,
    ):
        mock_post_json_request.return_value = {
            "message": {
                "content": '{"clarification_questions": []}',
            }
        }
        provider = OllamaProviderClient()

        provider.generate_clarification_questions(
            tenant_id=101,
            store_id=77,
            normalized_description="I want an online store",
            semantic_analysis={
                "description_language": "en",
                "description_sufficient": False,
                "detected_store_domains": [],
                "business_summary": "The idea needs clarification.",
                "target_audience": "",
                "product_direction": [],
                "blocking_missing_information": ["store_domain"],
                "ambiguities": ["The store domain is missing."],
            },
            clarification_round_count=1,
        )

        call_kwargs = mock_post_json_request.call_args.kwargs
        payload = call_kwargs["payload"]
        messages = payload["messages"]

        self.assertEqual(call_kwargs["url"], "https://ollama.example/api/chat")
        self.assertEqual(call_kwargs["timeout"], 21)
        self.assertEqual(payload["model"], "clarify-model")
        self.assertEqual(payload["options"]["temperature"], 0.2)
        self.assertIn("Clarify node", messages[0]["content"])
        self.assertIn("Ask only about real blocking gaps", messages[0]["content"])
        self.assertIn("normalized_description: I want an online store", messages[3]["content"])
        self.assertIn('"blocking_missing_information": ["store_domain"]', messages[4]["content"])
        self.assertIn("clarification_round_count: 1", messages[5]["content"])

    def test_clarification_questions_prompt_contract(self):
        messages = build_generate_clarification_questions_messages(
            tenant_id=101,
            store_id=77,
            normalized_description="I want an online store",
            semantic_analysis={
                "description_language": "en",
                "description_sufficient": False,
                "detected_store_domains": [],
                "business_summary": "The idea needs clarification.",
                "target_audience": "",
                "product_direction": [],
                "blocking_missing_information": ["store_domain"],
                "ambiguities": ["The store domain is missing."],
            },
            clarification_round_count=1,
        )
        system_prompt = messages[0]["content"].lower()

        for expected_text in (
            "clarify node",
            "smallest useful set",
            "ask only about real blocking gaps",
            "do not use a fixed questionnaire",
            "return this exact top-level key",
            "maximum 3 questions",
            "do not ask about store name",
            "question_key must exactly match one key",
        ):
            with self.subTest(expected_text=expected_text):
                self.assertIn(expected_text, system_prompt)

        self.assertIn("semantic_analysis:", messages[4]["content"])
        self.assertIn("clarification_round_count: 1", messages[5]["content"])

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="test-ollama-key",
        AI_API_URL="https://ollama.example/api/chat",
        AI_MODEL_NAME="agentic-generate-model",
        AI_TIMEOUT=25,
        AI_TEMPERATURE=0.05,
    )
    @patch("AI_Store_Creation_Service.providers._post_json_request")
    def test_ollama_generate_agentic_store_draft_uses_agentic_prompt_and_transport(
        self,
        mock_post_json_request,
    ):
        mock_post_json_request.return_value = {
            "message": {"content": '{"clarification_needed": false}'}
        }
        provider = OllamaProviderClient()

        provider.generate_agentic_store_draft(
            tenant_id=101,
            store_id=77,
            user_store_description="Build a modern beauty store",
            available_theme_templates=["Modern", "Classic"],
        )

        call_kwargs = mock_post_json_request.call_args.kwargs
        payload = call_kwargs["payload"]
        messages = payload["messages"]

        self.assertEqual(call_kwargs["url"], "https://ollama.example/api/chat")
        self.assertEqual(call_kwargs["timeout"], 25)
        self.assertEqual(payload["model"], "agentic-generate-model")
        self.assertEqual(payload["options"]["temperature"], 0.05)
        self.assertIn("Generate node", messages[0]["content"])
        self.assertIn("already analyzed and approved as sufficient", messages[0]["content"])
        self.assertIn("Do not ask clarification questions", messages[0]["content"])
        self.assertIn("Generate one complete draft-ready", messages[0]["content"])

    def test_agentic_generation_prompt_contains_no_clarification_decision_contract(self):
        messages = build_generate_agentic_store_draft_messages(
            tenant_id=101,
            store_id=77,
            user_store_description="Build a modern beauty store",
            available_theme_templates=["Modern", "Classic"],
        )
        system_prompt = messages[0]["content"].lower()

        for expected_text in (
            "generate node",
            "already analyzed and approved as sufficient",
            "do not reassess sufficiency",
            "complete draft-ready",
            "do not ask clarification questions",
            "clarification_needed` must be false",
            "clarification_questions` must be []",
        ):
            with self.subTest(expected_text=expected_text):
                self.assertIn(expected_text, system_prompt)

        for forbidden_text in (
            "return one of two results",
            "if clarification is needed",
            "if the description is not sufficient",
            "ask only the minimum high-value mcq",
            "clarification questions are only for essential ambiguity",
            "decide whether the description is sufficient",
            "clarification mode",
        ):
            with self.subTest(forbidden_text=forbidden_text):
                self.assertNotIn(forbidden_text, system_prompt)

    def test_ollama_response_is_normalized_to_existing_parser_shape(self):
        normalized = OllamaProviderClient._normalize_to_chat_completions_shape(
            {
                "message": {
                    "content": '{"store": {}, "clarification_needed": true}'
                }
            }
        )

        self.assertIn("choices", normalized)
        self.assertEqual(len(normalized["choices"]), 1)
        self.assertIn("message", normalized["choices"][0])
        self.assertIn("content", normalized["choices"][0]["message"])
        self.assertIn('{"store": {}, "clarification_needed": true}', normalized["choices"][0]["message"]["content"])

    def test_ollama_legacy_response_field_is_normalized_to_existing_parser_shape(self):
        normalized = OllamaProviderClient._normalize_to_chat_completions_shape(
            {"response": '{"ok": true}'}
        )

        self.assertEqual(
            normalized,
            {"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    def test_ollama_unsupported_response_shape_raises_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            OllamaProviderClient._normalize_to_chat_completions_shape({"done": True})

        self.assertIn(
            "Ollama response format is unsupported or missing message content",
            str(ctx.exception),
        )

    @override_settings(
        AI_PROVIDER="ollama",
        AI_API_KEY="",
    )
    @patch.dict("os.environ", {"OLLAMA_API_KEY": ""})
    def test_ollama_missing_api_key_raises_clear_error(self):
        provider = OllamaProviderClient()

        with self.assertRaises(ImproperlyConfigured) as ctx:
            provider._build_headers()

        self.assertIn("AI_API_KEY or OLLAMA_API_KEY is required", str(ctx.exception))


class AIInitialDescriptionValidationTests(TestCase):
    def test_validate_initial_description_rejects_non_string_input(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_initial_description(123)

        self.assertIn("text value", str(ctx.exception))

    def test_validate_initial_description_rejects_empty_string(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_initial_description("")

        self.assertIn("Store description is required", str(ctx.exception))

    def test_validate_initial_description_rejects_whitespace_only_string(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_initial_description(" \t\n  ")

        self.assertIn("Store description is required", str(ctx.exception))

    def test_validate_initial_description_rejects_fewer_than_five_words(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_initial_description("modern beauty store")

        self.assertIn("at least 5 words", str(ctx.exception))

    def test_validate_initial_description_accepts_exactly_five_words(self):
        result = validate_initial_description("modern beauty store for women")

        self.assertEqual(result, "modern beauty store for women")

    def test_validate_initial_description_accepts_more_than_five_words(self):
        result = validate_initial_description("modern beauty store for young women")

        self.assertEqual(result, "modern beauty store for young women")

    def test_validate_initial_description_normalizes_repeated_spaces(self):
        result = validate_initial_description("  modern   beauty\tstore\nfor   women  ")

        self.assertEqual(result, "modern beauty store for women")


class AIWorkflowBaseMixin:
    @staticmethod
    def _as_provider_response(payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ]
        }

    @staticmethod
    def _valid_full_draft_payload() -> dict:
        return {
            "store": {"name": "My Store", "description": "Desc"},
            "store_settings": {
                "currency": "USD",
                "language": "en",
                "timezone": "UTC",
            },
            "theme": {
                "theme_template": "Modern",
                "primary_color": "#112233",
                "secondary_color": "rgb(255, 255, 255)",
                "font_family": "Inter",
                "logo_url": "",
                "banner_url": "",
            },
            "categories": [{"name": "Clothes"}, {"name": "Shoes"}],
            "products": [
                {
                    "name": "T-Shirt",
                    "description": "Cotton shirt",
                    "price": 25.5,
                    "sku": "TS-001",
                    "category_name": "Clothes",
                    "stock_quantity": 5,
                    "image_url": "",
                },
                {
                    "name": "Sneakers",
                    "description": "Running shoes",
                    "price": 70,
                    "sku": "SN-001",
                    "category_name": "Shoes",
                    "stock_quantity": 3,
                    "image_url": "",
                },
            ],
            "clarification_needed": False,
            "clarification_questions": [],
        }

    @staticmethod
    def _clarification_payload() -> dict:
        return {
            "store": {},
            "store_settings": {},
            "theme": {},
            "categories": [],
            "products": [],
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }


class AIServiceFacadeCompatibilityTests(AIWorkflowBaseMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="facade_owner",
            email="facade_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

    def _create_store(self) -> Store:
        return Store.objects.create(
            owner=self.user,
            tenant_id=self.user.tenant_id,
            name="AI Draft Store",
            description="",
            status="draft",
        )

    def _seed_templates(self):
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    def _prepare_clarification_state(
        self,
        store: Store,
        round_count: int = 0,
        repair_attempt_count: int | None = None,
    ):
        save_ai_draft(store.id, self._clarification_payload())
        metadata = {
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "current_step": "analyzing_description",
            "mode": "clarification",
            "is_fallback": False,
            "clarification_round_count": round_count,
            "original_user_store_description": "Original store description",
        }
        if repair_attempt_count is not None:
            metadata["repair_attempt_count"] = repair_attempt_count
        save_ai_draft_meta(store.id, metadata)

    def _dependency_originals(self) -> dict[str, object]:
        return {
            "provider": workflow_services.get_ai_provider_client,
            "workflow_clarification_limit": workflow_services.MAX_CLARIFICATION_ROUNDS,
            "workflow_repair_limit": workflow_services.MAX_REPAIR_ATTEMPTS,
            "metadata_clarification_limit": metadata_services.MAX_CLARIFICATION_ROUNDS,
            "metadata_repair_limit": metadata_services.MAX_REPAIR_ATTEMPTS,
        }

    def _assert_dependencies_restored(self, originals: dict[str, object]):
        self.assertIs(workflow_services.get_ai_provider_client, originals["provider"])
        self.assertEqual(
            workflow_services.MAX_CLARIFICATION_ROUNDS,
            originals["workflow_clarification_limit"],
        )
        self.assertEqual(
            workflow_services.MAX_REPAIR_ATTEMPTS,
            originals["workflow_repair_limit"],
        )
        self.assertEqual(
            metadata_services.MAX_CLARIFICATION_ROUNDS,
            originals["metadata_clarification_limit"],
        )
        self.assertEqual(
            metadata_services.MAX_REPAIR_ATTEMPTS,
            originals["metadata_repair_limit"],
        )

    def test_public_facade_signatures_match_implementation_signatures(self):
        facade_targets = [
            ("derive_store_name_from_description", workflow_services),
            ("create_draft_store_for_ai_flow", workflow_services),
            ("start_ai_draft_workflow", workflow_services),
            ("generate_initial_store_draft", workflow_services),
            ("get_current_ai_draft", workflow_services),
            ("process_clarification_round", workflow_services),
            ("regenerate_store_draft", workflow_services),
            ("regenerate_store_draft_section", workflow_services),
            ("apply_current_ai_draft_store_core", apply_services),
            ("apply_current_ai_draft_categories", apply_services),
            ("apply_current_ai_draft_products", apply_services),
            ("apply_current_ai_draft_to_store", apply_services),
        ]

        for function_name, implementation_module in facade_targets:
            with self.subTest(function_name=function_name):
                self.assertEqual(
                    inspect.signature(getattr(services, function_name)),
                    inspect.signature(getattr(implementation_module, function_name)),
                )

    def test_keyword_only_facade_arguments_remain_enforced(self):
        with self.assertRaises(TypeError):
            services.start_ai_draft_workflow(
                self.user,
                self.user.tenant_id,
                "I want to build a modern beauty store",
            )

        with self.assertRaises(TypeError):
            services.create_draft_store_for_ai_flow(
                self.user,
                self.user.tenant_id,
                "My Draft Store",
            )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_provider_patch_through_services_is_used_and_restored_after_success(
        self,
        mock_get_provider,
    ):
        originals = self._dependency_originals()
        self._seed_templates()
        store = self._create_store()
        mock_get_provider.return_value.generate_store_draft.return_value = (
            self._as_provider_response(self._valid_full_draft_payload())
        )

        result = services.generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=self.user.tenant_id,
            user_store_description="I want to build a modern beauty store",
        )

        self.assertEqual(result["store"]["name"], "My Store")
        mock_get_provider.assert_called_once()
        mock_get_provider.return_value.generate_store_draft.assert_called_once()
        self._assert_dependencies_restored(originals)

    def test_provider_patch_is_restored_after_delegated_exception(self):
        originals = self._dependency_originals()
        store = self._create_store()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client"):
            with patch(
                "AI_Store_Creation_Service.workflow_services.generate_initial_store_draft",
                side_effect=RuntimeError("delegated failure"),
            ):
                with self.assertRaises(RuntimeError):
                    services.generate_initial_store_draft(
                        store_id=store.id,
                        user=self.user,
                        tenant_id=self.user.tenant_id,
                        user_store_description="I want to build a modern beauty store",
                    )

                self._assert_dependencies_restored(originals)

    @patch("AI_Store_Creation_Service.services.MAX_REPAIR_ATTEMPTS", 7)
    @patch("AI_Store_Creation_Service.services.MAX_CLARIFICATION_ROUNDS", 2)
    def test_workflow_limit_patches_are_used_and_restored_after_success(self):
        originals = self._dependency_originals()
        store = self._create_store()
        self._prepare_clarification_state(
            store,
            round_count=2,
            repair_attempt_count=4,
        )

        result = services.process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=self.user.tenant_id,
            clarification_answers="Any answer",
        )

        self.assertFalse(result["clarification_needed"])
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["max_clarification_rounds"], 2)
        self.assertEqual(meta["max_repair_attempts"], 7)
        self._assert_dependencies_restored(originals)

    @patch("AI_Store_Creation_Service.services.MAX_REPAIR_ATTEMPTS", 9)
    def test_repair_limit_patch_flows_independently_to_metadata(self):
        originals = self._dependency_originals()
        store = self._create_store()
        self._prepare_clarification_state(
            store,
            round_count=MAX_CLARIFICATION_ROUNDS,
            repair_attempt_count=4,
        )

        services.process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=self.user.tenant_id,
            clarification_answers="Any answer",
        )

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(meta["max_repair_attempts"], 9)
        self._assert_dependencies_restored(originals)

    def test_workflow_limit_patches_are_restored_after_delegated_exception(self):
        originals = self._dependency_originals()
        store = self._create_store()

        with patch("AI_Store_Creation_Service.services.MAX_CLARIFICATION_ROUNDS", 1):
            with patch("AI_Store_Creation_Service.services.MAX_REPAIR_ATTEMPTS", 8):
                with patch(
                    "AI_Store_Creation_Service.workflow_services.process_clarification_round",
                    side_effect=RuntimeError("delegated failure"),
                ):
                    with self.assertRaises(RuntimeError):
                        services.process_clarification_round(
                            store_id=store.id,
                            user=self.user,
                            tenant_id=self.user.tenant_id,
                            clarification_answers="Any answer",
                        )

                    self._assert_dependencies_restored(originals)

    def test_direct_workflow_call_after_facade_patch_uses_original_dependencies(self):
        originals = self._dependency_originals()
        self._seed_templates()
        first_store = self._create_store()
        self._prepare_clarification_state(first_store, round_count=1)

        with patch("AI_Store_Creation_Service.services.MAX_CLARIFICATION_ROUNDS", 1):
            result = services.process_clarification_round(
                store_id=first_store.id,
                user=self.user,
                tenant_id=self.user.tenant_id,
                clarification_answers="Any answer",
            )
            self.assertFalse(result["clarification_needed"])

        self._assert_dependencies_restored(originals)

        second_store = self._create_store()
        self._prepare_clarification_state(second_store, round_count=1)
        with patch(
            "AI_Store_Creation_Service.workflow_services.get_ai_provider_client"
        ) as direct_get_provider:
            direct_get_provider.return_value.clarify_store_draft.return_value = (
                self._as_provider_response(self._valid_full_draft_payload())
            )

            result = workflow_services.process_clarification_round(
                store_id=second_store.id,
                user=self.user,
                tenant_id=self.user.tenant_id,
                clarification_answers="Enough information is available now",
            )

        direct_get_provider.return_value.clarify_store_draft.assert_called_once()
        self.assertFalse(result["clarification_needed"])
        meta = get_ai_draft_meta(second_store.id)
        self.assertEqual(meta["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)


class AICreationServicesTests(AIWorkflowBaseMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="ai_owner",
            email="ai_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

    def _create_store(self) -> Store:
        return Store.objects.create(
            owner=self.user,
            tenant_id=self.user.tenant_id,
            name="AI Draft Store",
            description="",
            status="draft",
        )

    def _seed_templates(self):
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    def _prepare_clarification_state(
        self,
        store: Store,
        round_count: int = 0,
        repair_attempt_count: int | None = None,
    ):
        save_ai_draft(store.id, self._clarification_payload())
        metadata = {
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "current_step": "analyzing_description",
            "mode": "clarification",
            "is_fallback": False,
            "clarification_round_count": round_count,
            "original_user_store_description": "Original store description",
        }
        if repair_attempt_count is not None:
            metadata["repair_attempt_count"] = repair_attempt_count
        save_ai_draft_meta(store.id, metadata)

    def _prepare_regeneration_state(
        self,
        store: Store,
        *,
        current_draft: dict | None = None,
        original_description: str = "Original store description",
        clarification_history: list[dict] | None = None,
        latest_clarification_input: str = "Prefer minimal style",
        clarification_round_count: int = 1,
        repair_attempt_count: int | None = None,
    ):
        save_ai_draft(store.id, current_draft or self._valid_full_draft_payload())
        metadata = {
            "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
            "current_step": "analyzing_description",
            "mode": "clarification",
            "is_fallback": False,
            "clarification_round_count": clarification_round_count,
            "original_user_store_description": original_description,
            "latest_clarification_input": latest_clarification_input,
            "clarification_history": clarification_history or [],
        }
        if repair_attempt_count is not None:
            metadata["repair_attempt_count"] = repair_attempt_count
        save_ai_draft_meta(store.id, metadata)

    def _prepare_draft_ready_state(
        self,
        store: Store,
        *,
        current_draft: dict | None = None,
        original_description: str = "Original store description",
        clarification_history: list[dict] | None = None,
        latest_clarification_input: str = "Prefer minimal style",
        clarification_round_count: int = 1,
        repair_attempt_count: int | None = None,
    ):
        save_ai_draft(store.id, current_draft or self._valid_full_draft_payload())
        metadata = {
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": "setting_up_store_configuration",
            "mode": "draft_ready",
            "is_fallback": False,
            "clarification_round_count": clarification_round_count,
            "original_user_store_description": original_description,
            "latest_clarification_input": latest_clarification_input,
            "clarification_history": clarification_history or [],
        }
        if repair_attempt_count is not None:
            metadata["repair_attempt_count"] = repair_attempt_count
        save_ai_draft_meta(store.id, metadata)

    def test_create_draft_store_success(self):
        store = create_draft_store_for_ai_flow(
            user=self.user,
            tenant_id=101,
            name="My Draft",
            description="Test description",
        )
        self.assertTrue(Store.objects.filter(id=store.id).exists())
        self.assertEqual(store.owner_id, self.user.id)
        self.assertEqual(store.tenant_id, 101)
        self.assertEqual(store.status, "draft")

    def test_create_draft_store_rejects_invalid_contexts(self):
        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=AnonymousUser(), tenant_id=101, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=None, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=999, name="My Draft")

        with self.assertRaises(ValidationError):
            create_draft_store_for_ai_flow(user=self.user, tenant_id=101, name="   ")

    def test_derive_store_name_extracts_explicit_name(self):
        derived = derive_store_name_from_description(
            'Please create a new store, store name is "Noor Beauty".'
        )
        self.assertEqual(derived, "Noor Beauty")

    def test_derive_store_name_returns_safe_non_empty_fallback(self):
        derived = derive_store_name_from_description("This is a very vague description.")
        self.assertIsInstance(derived, str)
        self.assertTrue(derived.strip())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_ai_draft_workflow_creates_store_with_locally_derived_name(self, mock_get_provider):
        self._seed_templates()
        payload = self._clarification_payload()
        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        draft_state = start_ai_draft_workflow(
            user=self.user,
            tenant_id=101,
            user_store_description="I want to build an electronics and gadgets store.",
        )

        self.assertEqual(set(draft_state.keys()), {"store_id", "draft_payload", "draft_metadata"})
        created_store = Store.objects.get(id=draft_state["store_id"])
        self.assertTrue(created_store.name.strip())
        self.assertEqual(created_store.owner_id, self.user.id)
        self.assertEqual(created_store.tenant_id, 101)
        self.assertEqual(created_store.status, "draft")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_ai_draft_workflow_missing_templates_returns_recoverable_state(
        self,
        mock_get_provider,
    ):
        ThemeTemplate.objects.all().delete()
        initial_store_count = Store.objects.count()

        draft_state = start_ai_draft_workflow(
            user=self.user,
            tenant_id=101,
            user_store_description="I want to build a modern skincare products store.",
        )

        mock_get_provider.assert_not_called()
        self.assertEqual(Store.objects.count(), initial_store_count + 1)
        self.assertEqual(set(draft_state.keys()), {"store_id", "draft_payload", "draft_metadata"})
        self.assertIsInstance(draft_state["store_id"], int)

        created_store = Store.objects.get(id=draft_state["store_id"])
        self.assertEqual(created_store.owner_id, self.user.id)
        self.assertEqual(created_store.tenant_id, 101)
        self.assertEqual(created_store.status, "draft")

        payload = draft_state["draft_payload"]
        metadata = draft_state["draft_metadata"]
        self.assertFalse(payload["clarification_needed"])
        self.assertEqual(payload["clarification_questions"], [])
        self.assertEqual(payload["error_code"], THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE)
        self.assertEqual(payload["user_message"], THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE)
        self.assertTrue(payload["retry_allowed"])
        self.assertTrue(payload["manual_edit_allowed"])

        self.assertEqual(metadata["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(metadata["current_step"], "recoverable_failure")
        self.assertEqual(metadata["mode"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(metadata["is_fallback"])
        self.assertEqual(metadata["error_code"], THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE)
        self.assertEqual(metadata["user_message"], THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE)
        self.assertEqual(metadata["clarification_round_count"], 0)
        self.assertEqual(metadata["repair_attempt_count"], 0)
        self.assertEqual(metadata["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(metadata["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)
        self.assertEqual(
            metadata["original_user_store_description"],
            "I want to build a modern skincare products store.",
        )

        self.assertEqual(get_ai_draft(created_store.id), payload)
        self.assertEqual(get_ai_draft_meta(created_store.id), metadata)

        audit = AIStoreAuditLog.objects.filter(
            store_id=created_store.id,
            action="start_draft",
            status="failed",
        ).latest("id")
        self.assertIn("No available theme templates found", audit.message)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_ai_draft_workflow_rejects_short_description_without_side_effects(
        self,
        mock_get_provider,
    ):
        initial_store_count = Store.objects.count()

        with self.assertRaises(ValidationError) as ctx:
            start_ai_draft_workflow(
                user=self.user,
                tenant_id=101,
                user_store_description="too short",
            )

        self.assertIn("at least 5 words", str(ctx.exception))
        self.assertEqual(Store.objects.count(), initial_store_count)
        mock_get_provider.assert_not_called()

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_rejects_short_description_before_provider(
        self,
        mock_get_provider,
    ):
        store = self._create_store()

        with self.assertRaises(ValidationError) as ctx:
            generate_initial_store_draft(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                user_store_description="too short",
            )

        self.assertIn("at least 5 words", str(ctx.exception))
        self.assertIsNone(get_ai_draft(store.id))
        mock_get_provider.assert_not_called()

    def test_clarify_prompt_contract_requires_full_draft_when_information_is_sufficient(self):
        messages = build_clarify_store_draft_messages(
            tenant_id=101,
            store_id=1,
            current_draft=self._clarification_payload(),
            prompt="Store type is fashion and all details are clear",
            context={"original_store_description": "Fashion store"},
        )
        system_prompt = messages[0]["content"]
        self.assertIn("return a complete valid draft payload now", system_prompt)
        self.assertIn('"clarification_needed": false', system_prompt)
        self.assertIn('"clarification_questions": []', system_prompt)

    def test_full_generation_prompt_contract_mentions_targeted_reliability_constraints(self):
        messages = build_generate_store_draft_messages(
            tenant_id=101,
            store_id=1,
            user_store_description="Build me a beauty store",
            available_theme_templates=["Modern", "Classic"],
        )
        system_prompt = messages[0]["content"]
        self.assertIn("Generate between 2 and 4 products.", system_prompt)
        self.assertIn("Never return more than 4 products.", system_prompt)
        self.assertIn("`theme_template`", system_prompt)
        self.assertIn("`primary_color`", system_prompt)
        self.assertIn("non-empty string", system_prompt)
        self.assertIn("no blank strings, nulls, or empty values", system_prompt)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_success_full_draft(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_canonicalizes_theme_template_name(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "  modern  "

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["theme"]["theme_template"], "Modern")
        self.assertEqual(get_ai_draft(store.id)["theme"]["theme_template"], "Modern")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_normalizes_missing_product_image_url(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0].pop("image_url", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["products"][0]["image_url"], "")
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_normalizes_null_product_image_url(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0]["image_url"] = None

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["products"][0]["image_url"], "")
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_keeps_valid_product_image_url_unchanged(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0]["image_url"] = "https://cdn.example.com/p-1.png"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["products"][0]["image_url"], "https://cdn.example.com/p-1.png")
        self.assertEqual(result["products"][1]["image_url"], "")

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_still_fails_for_core_invalid_product_payload(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"][0].pop("sku", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(
            result,
            build_ai_recoverable_failure_payload(error_code="ai_validation_failed"),
        )
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(meta["error_code"], "ai_validation_failed")
        self.assertEqual(meta["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotIn("reason", meta)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_trims_products_to_allowed_max(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["products"].extend(
            [
                {
                    "name": "Hat",
                    "description": "Sport hat",
                    "price": 15,
                    "sku": "HT-001",
                    "category_name": "Clothes",
                    "stock_quantity": 7,
                    "image_url": "",
                },
                {
                    "name": "Socks",
                    "description": "Daily socks",
                    "price": 8,
                    "sku": "SK-001",
                    "category_name": "Clothes",
                    "stock_quantity": 20,
                    "image_url": "",
                },
                {
                    "name": "Backpack",
                    "description": "Travel backpack",
                    "price": 42,
                    "sku": "BP-001",
                    "category_name": "Shoes",
                    "stock_quantity": 4,
                    "image_url": "",
                },
            ]
        )

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(len(result["products"]), 4)
        self.assertEqual(result["products"][-1]["sku"], "SK-001")
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_cleans_clarification_options_before_validation(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._clarification_payload()
        payload["clarification_questions"][0]["options"] = ["Fashion", "", None, "  ", "Electronics"]

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertTrue(result["clarification_needed"])
        self.assertEqual(
            result["clarification_questions"][0]["options"],
            ["Fashion", "Electronics"],
        )
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_NEEDS_CLARIFICATION,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_resolves_theme_template_from_style_hint(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "   "
        payload["theme"]["style"] = " modern "

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["theme"]["theme_template"], "Modern")
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_unresolved_theme_template_still_fails(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["theme"]["theme_template"] = "   "
        payload["theme"]["style"] = "futuristic-neon"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(
            result,
            build_ai_recoverable_failure_payload(error_code="ai_validation_failed"),
        )
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(meta["error_code"], "ai_validation_failed")
        self.assertNotIn("reason", meta)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_keeps_core_validation_strict_for_invalid_categories(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["categories"] = [{"name": "Only One Category"}]
        payload["products"][0]["category_name"] = "Only One Category"
        payload["products"][1]["category_name"] = "Only One Category"

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(
            result,
            build_ai_recoverable_failure_payload(error_code="ai_validation_failed"),
        )
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(meta["error_code"], "ai_validation_failed")
        self.assertNotIn("reason", meta)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_success_clarification_mode(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        payload = self._clarification_payload()

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_clarification_payload_with_missing_structural_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = {
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                }
            ],
        }

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertEqual(result["clarification_needed"], True)
        self.assertIn("store", result)
        self.assertIn("store_settings", result)
        self.assertIn("theme", result)
        self.assertIn("categories", result)
        self.assertIn("products", result)
        self.assertEqual(result["store"], {})
        self.assertEqual(result["categories"], [])
        self.assertEqual(get_ai_draft(store.id), result)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(meta["mode"], "clarification")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_clarification_questions_with_extra_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = {
            "clarification_needed": True,
            "clarification_questions": [
                {
                    "question_key": "store_type",
                    "question_text": "What type of store?",
                    "options": ["Fashion", "Electronics"],
                    "hint": "Choose one",
                    "priority": 1,
                }
            ],
        }

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Store idea is not clear yet",
        )

        self.assertTrue(result["clarification_needed"])
        self.assertEqual(result["clarification_questions"][0]["question_key"], "store_type")
        self.assertIn("hint", result["clarification_questions"][0])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_accepts_full_payload_without_clarification_keys(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload.pop("clarification_needed", None)
        payload.pop("clarification_questions", None)

        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            payload
        )

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="A modern sportswear store for athletes",
        )

        self.assertEqual(result["clarification_needed"], False)
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(result["store"]["name"], "My Store")

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_fallback_on_provider_failure(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()

        mock_get_provider.return_value.generate_store_draft.side_effect = RuntimeError("provider timeout")

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any valid store description with enough words",
        )

        fallback = build_ai_recoverable_failure_payload(
            error_code=RECOVERABLE_FAILURE_ERROR_CODE
        )
        self.assertEqual(result, fallback)
        self.assertEqual(get_ai_draft(store.id), fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(meta["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(meta["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertTrue(meta["retry_allowed"])
        self.assertTrue(meta["manual_edit_allowed"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_generate_initial_store_draft_malformed_json_is_recoverable_failure(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        mock_get_provider.return_value.generate_store_draft.return_value = {
            "choices": [{"message": {"content": "not valid json"}}]
        }

        result = generate_initial_store_draft(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            user_store_description="Any valid store description with enough words",
        )

        self.assertEqual(
            result,
            build_ai_recoverable_failure_payload(error_code="ai_output_parse_failed"),
        )
        self.assertFalse(result["clarification_needed"])
        self.assertEqual(result["clarification_questions"], [])

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(meta["error_code"], "ai_output_parse_failed")
        self.assertEqual(meta["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotIn("not valid json", meta["user_message"])

    def test_get_current_ai_draft_success(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        metadata = {
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": "setting_up_store_configuration",
            "mode": "draft_ready",
            "original_user_store_description": "Sportswear store",
        }
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(store.id, metadata)

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(
            result["draft_metadata"],
            {
                **metadata,
                "clarification_round_count": 0,
                "repair_attempt_count": 0,
                "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
                "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                "is_fallback": False,
                "clarification_history": [],
            },
        )

    def test_get_current_ai_draft_normalizes_legacy_draft_ready_status(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": "draft_ready",
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Sportswear store",
            },
        )

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(
            result["draft_metadata"]["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )
        self.assertEqual(
            get_ai_draft_meta(store.id)["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )

    def test_get_current_ai_draft_migrates_legacy_clarification_fallback(self):
        store = self._create_store()
        legacy_payload = self._clarification_payload()
        save_ai_draft(store.id, legacy_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": True,
                "clarification_round_count": 2,
                "repair_attempt_count": 1,
                "original_user_store_description": "Sportswear store",
                "latest_clarification_input": "Target adults",
                "clarification_history": [{"round": 2, "clarification_input": "Target adults"}],
            },
        )

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["draft_metadata"]["mode"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(result["draft_metadata"]["is_fallback"])
        self.assertEqual(result["draft_metadata"]["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(result["draft_metadata"]["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertTrue(result["draft_metadata"]["retry_allowed"])
        self.assertTrue(result["draft_metadata"]["manual_edit_allowed"])
        self.assertEqual(result["draft_metadata"]["clarification_round_count"], 2)
        self.assertEqual(result["draft_metadata"]["repair_attempt_count"], 1)
        self.assertEqual(
            result["draft_metadata"]["clarification_history"],
            [{"round": 2, "clarification_input": "Target adults"}],
        )

        self.assertFalse(result["draft_payload"]["clarification_needed"])
        self.assertEqual(result["draft_payload"]["clarification_questions"], [])
        self.assertEqual(result["draft_payload"]["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertTrue(result["draft_payload"]["retry_allowed"])
        self.assertTrue(result["draft_payload"]["manual_edit_allowed"])
        self.assertEqual(get_ai_draft(store.id), result["draft_payload"])
        self.assertEqual(get_ai_draft_meta(store.id), result["draft_metadata"])

    def test_get_current_ai_draft_preserves_genuine_clarification(self):
        store = self._create_store()
        payload = self._clarification_payload()
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "original_user_store_description": "Sportswear store",
            },
        )

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertFalse(result["draft_metadata"]["is_fallback"])
        self.assertTrue(result["draft_payload"]["clarification_needed"])
        self.assertTrue(result["draft_payload"]["clarification_questions"])

    def test_get_current_ai_draft_preserves_current_failed_recoverable(self):
        store = self._create_store()
        payload = build_ai_recoverable_failure_payload(
            error_code=RECOVERABLE_FAILURE_ERROR_CODE
        )
        metadata = {
            "status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
            "current_step": "recoverable_failure",
            "mode": WORKFLOW_STATUS_FAILED_RECOVERABLE,
            "is_fallback": True,
            "error_code": RECOVERABLE_FAILURE_ERROR_CODE,
            "user_message": RECOVERABLE_FAILURE_USER_MESSAGE,
            "retry_allowed": True,
            "manual_edit_allowed": True,
            "original_user_store_description": "Sportswear store",
        }
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(store.id, metadata)

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(result["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(result["draft_metadata"]["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(get_ai_draft(store.id), payload)

    def test_get_current_ai_draft_rebuilds_missing_metadata_when_draft_exists(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, payload)

        result = get_current_ai_draft(store.id, self.user, 101)

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["draft_payload"], payload)
        self.assertEqual(
            result["draft_metadata"]["status"],
            WORKFLOW_STATUS_READY_FOR_REVIEW,
        )
        self.assertEqual(result["draft_metadata"]["mode"], "draft_ready")
        self.assertTrue(result["draft_metadata"]["original_user_store_description"].strip())
        self.assertEqual(result["draft_metadata"]["clarification_round_count"], 0)
        self.assertEqual(result["draft_metadata"]["repair_attempt_count"], 0)
        self.assertEqual(
            result["draft_metadata"]["max_clarification_rounds"],
            MAX_CLARIFICATION_ROUNDS,
        )
        self.assertEqual(result["draft_metadata"]["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_stays_in_clarification(self, mock_get_provider):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0, repair_attempt_count=2)

        next_payload = self._clarification_payload()
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(next_payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        self.assertEqual(result, next_payload)
        self.assertEqual(get_ai_draft(store.id), next_payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(meta["clarification_round_count"], 1)
        self.assertEqual(meta["repair_attempt_count"], 2)
        self.assertEqual(meta["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(meta["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_rebuilds_missing_metadata_when_draft_exists(
        self, mock_get_provider
    ):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(
            self._clarification_payload()
        )

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        self.assertTrue(result["clarification_needed"])
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_NEEDS_CLARIFICATION)
        self.assertEqual(meta["mode"], "clarification")
        self.assertTrue(meta["original_user_store_description"].strip())
        self.assertEqual(meta["clarification_round_count"], 1)
        self.assertEqual(meta["repair_attempt_count"], 0)
        self.assertEqual(meta["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(meta["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_provider_failure_keeps_round_tracking_consistent(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._prepare_clarification_state(store, round_count=0, repair_attempt_count=2)
        mock_get_provider.return_value.clarify_store_draft.side_effect = RuntimeError("provider timeout")

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={"store_type": "Fashion"},
        )

        fallback = build_ai_recoverable_failure_payload(
            error_code=RECOVERABLE_FAILURE_ERROR_CODE
        )
        self.assertEqual(result, fallback)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertFalse(result["clarification_needed"])
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(meta["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(meta["clarification_round_count"], 1)
        self.assertEqual(meta["repair_attempt_count"], 2)
        self.assertEqual(meta["clarification_history"][0]["round"], 1)
        self.assertEqual(meta["clarification_round_count"], meta["clarification_history"][-1]["round"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_transitions_to_draft_ready(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=0)

        payload = self._valid_full_draft_payload()
        mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Target audience: young adults",
        )

        self.assertEqual(result, payload)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertEqual(meta["clarification_round_count"], 1)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_final_round_generates_draft_ready_when_ai_asks_again(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=MAX_CLARIFICATION_ROUNDS - 1)

        clarification_payload = self._clarification_payload()
        final_payload = self._valid_full_draft_payload()
        provider = mock_get_provider.return_value
        provider.clarify_store_draft.return_value = self._as_provider_response(clarification_payload)
        provider.regenerate_store_draft.return_value = self._as_provider_response(final_payload)

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={
                "secondary_color": "#FFFFFF",
                "font_family": "Inter",
            },
        )

        self.assertEqual(result, final_payload)
        self.assertEqual(get_ai_draft(store.id), final_payload)
        provider.regenerate_store_draft.assert_called_once()

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertFalse(meta["is_fallback"])
        self.assertEqual(meta["clarification_round_count"], MAX_CLARIFICATION_ROUNDS)
        self.assertTrue(meta["final_clarification_round"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_process_clarification_round_final_round_repairs_invalid_final_payload(
        self,
        mock_get_provider,
    ):
        store = self._create_store()
        self._seed_templates()
        self._prepare_clarification_state(store, round_count=MAX_CLARIFICATION_ROUNDS - 1)

        clarification_payload = self._clarification_payload()
        invalid_final_payload = self._valid_full_draft_payload()
        invalid_final_payload["categories"] = []
        final_payload = self._valid_full_draft_payload()
        provider = mock_get_provider.return_value
        provider.clarify_store_draft.return_value = self._as_provider_response(clarification_payload)
        provider.regenerate_store_draft.side_effect = [
            self._as_provider_response(invalid_final_payload),
            self._as_provider_response(final_payload),
        ]

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers={
                "theme_template": "Modern",
                "secondary_color": "#FFFFFF",
                "timezone": "UTC",
            },
        )

        self.assertEqual(result, final_payload)
        self.assertEqual(provider.regenerate_store_draft.call_count, 2)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertFalse(meta["is_fallback"])
        self.assertEqual(meta["clarification_round_count"], MAX_CLARIFICATION_ROUNDS)

    def test_process_clarification_round_enforces_round_limit(self):
        store = self._create_store()
        self._prepare_clarification_state(
            store,
            round_count=MAX_CLARIFICATION_ROUNDS,
            repair_attempt_count=2,
        )

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        fallback = build_ai_recoverable_failure_payload(
            error_code="clarification_limit_reached",
            user_message="The clarification limit was reached. You can retry or edit the draft manually.",
        )
        self.assertEqual(result, fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(meta["error_code"], "clarification_limit_reached")
        self.assertFalse(result["clarification_needed"])
        self.assertEqual(result["clarification_questions"], [])
        self.assertEqual(meta["clarification_round_count"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(meta["repair_attempt_count"], 2)
        self.assertEqual(meta["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(meta["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

    @patch("AI_Store_Creation_Service.services.MAX_REPAIR_ATTEMPTS", 7)
    @patch("AI_Store_Creation_Service.services.MAX_CLARIFICATION_ROUNDS", 2)
    def test_workflow_limits_are_independently_configurable(self):
        store = self._create_store()
        self._prepare_clarification_state(
            store,
            round_count=2,
            repair_attempt_count=4,
        )

        result = process_clarification_round(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            clarification_answers="Any answer",
        )

        fallback = build_ai_recoverable_failure_payload(
            error_code="clarification_limit_reached",
            user_message="The clarification limit was reached. You can retry or edit the draft manually.",
        )
        self.assertEqual(result, fallback)
        self.assertEqual(get_ai_draft(store.id), fallback)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(meta["is_fallback"])
        self.assertEqual(meta["error_code"], "clarification_limit_reached")
        self.assertEqual(meta["clarification_round_count"], 2)
        self.assertEqual(meta["repair_attempt_count"], 4)
        self.assertEqual(meta["max_clarification_rounds"], 2)
        self.assertEqual(meta["max_repair_attempts"], 7)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_success(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        self._prepare_regeneration_state(
            store,
            current_draft=self._clarification_payload(),
            repair_attempt_count=2,
        )

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Regenerated Store"
        mock_get_provider.return_value.regenerate_store_draft.return_value = self._as_provider_response(payload)

        result = regenerate_store_draft(store.id, self.user, 101)

        self.assertEqual(result, payload)
        self.assertEqual(get_ai_draft(store.id), payload)

        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["repair_attempt_count"], 2)
        self.assertEqual(meta["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_success_theme(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(
            store,
            current_draft=base_payload,
            repair_attempt_count=2,
        )
        stale_meta = get_ai_draft_meta(store.id)
        stale_meta.update(
            {
                "last_operation": LAST_OPERATION_PARTIAL_REGENERATION,
                "last_operation_status": WORKFLOW_STATUS_FAILED_RECOVERABLE,
                "last_operation_error_code": PARTIAL_REGENERATION_FAILED_ERROR_CODE,
                "last_operation_user_message": PARTIAL_REGENERATION_FAILED_USER_MESSAGE,
                "retry_allowed": True,
            }
        )
        save_ai_draft_meta(store.id, stale_meta)

        replacement_theme = {
            "theme_template": "Classic",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": replacement_theme}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="theme",
        )

        self.assertEqual(result["theme"], replacement_theme)
        self.assertEqual(result["categories"], base_payload["categories"])
        self.assertEqual(result["products"], base_payload["products"])
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["repair_attempt_count"], 2)
        self.assertEqual(meta["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["last_partial_regeneration_target_section"], "theme")
        self.assertEqual(meta["last_operation"], LAST_OPERATION_PARTIAL_REGENERATION)
        self.assertEqual(meta["last_operation_status"], LAST_OPERATION_STATUS_COMPLETED)
        self.assertNotIn("last_operation_error_code", meta)
        self.assertNotIn("last_operation_user_message", meta)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_rebuilds_missing_metadata_when_draft_exists(
        self, mock_get_provider
    ):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, base_payload)

        replacement_theme = {
            "theme_template": " classic ",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }
        mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
            {"theme": replacement_theme}
        )

        result = regenerate_store_draft_section(
            store_id=store.id,
            user=self.user,
            tenant_id=101,
            target_section="theme",
        )

        self.assertEqual(result["theme"]["theme_template"], "Classic")
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["mode"], "draft_ready")
        self.assertTrue(meta["original_user_store_description"].strip())

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_store_draft_section_failure_keeps_draft_unchanged(self, mock_get_provider):
        store = self._create_store()
        self._seed_templates()
        base_payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=base_payload)
        before = get_ai_draft(store.id)

        mock_get_provider.return_value.regenerate_store_draft_section.side_effect = RuntimeError("provider timeout")

        with self.assertRaises(ValidationError) as ctx:
            regenerate_store_draft_section(
                store_id=store.id,
                user=self.user,
                tenant_id=101,
                target_section="theme",
            )

        self.assertIn(PARTIAL_REGENERATION_FAILED_USER_MESSAGE, str(ctx.exception))
        self.assertEqual(get_ai_draft(store.id), before)
        meta = get_ai_draft_meta(store.id)
        self.assertEqual(meta["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertEqual(meta["last_operation"], LAST_OPERATION_PARTIAL_REGENERATION)
        self.assertEqual(meta["last_operation_status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertEqual(
            meta["last_operation_error_code"],
            PARTIAL_REGENERATION_FAILED_ERROR_CODE,
        )
        self.assertEqual(
            meta["last_operation_user_message"],
            PARTIAL_REGENERATION_FAILED_USER_MESSAGE,
        )
        self.assertTrue(meta["retry_allowed"])
        self.assertEqual(meta["last_partial_regeneration_target_section"], "theme")
        self.assertNotIn("last_partial_regeneration_error", meta)
        self.assertNotIn("provider timeout", json.dumps(meta))
        self.assertIn(
            "provider timeout",
            AIStoreAuditLog.objects.filter(
                store_id=store.id,
                action="partial_regenerate",
                status="failed",
            ).latest("id").message,
        )

    def test_apply_current_ai_draft_store_core_success(self):
        store = self._create_store()
        self._seed_templates()

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Applied Store Name"
        payload["store"]["description"] = "Applied description"
        payload["store_settings"]["currency"] = "SYP"
        payload["store_settings"]["language"] = "ar"
        payload["store_settings"]["timezone"] = "Asia/Damascus"
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_store_core(store.id, self.user, 101)

        store.refresh_from_db()
        settings = StoreSettings.objects.get(store=store)
        self.assertEqual(store.name, "Applied Store Name")
        self.assertEqual(store.description, "Applied description")
        self.assertEqual(store.status, "draft")
        self.assertEqual(settings.currency, "SYP")
        self.assertEqual(settings.language, "ar")
        self.assertEqual(settings.timezone, "Asia/Damascus")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        self.assertEqual(result["draft_status"], WORKFLOW_STATUS_READY_FOR_REVIEW)
        self.assertNotIn("store_settings", result)

    def test_apply_current_ai_draft_store_core_updates_existing_settings_preserving_unrelated_fields(self):
        store = self._create_store()
        self._seed_templates()
        settings = StoreSettings.objects.create(
            store=store,
            store_email="support@example.com",
            store_phone="+963999999999",
            currency="USD",
            language="en",
            timezone="UTC",
            email_notifications=False,
            order_notifications=False,
            marketing_notifications=True,
            two_factor_auth=True,
        )

        payload = self._valid_full_draft_payload()
        payload["store_settings"]["currency"] = "EUR"
        payload["store_settings"]["language"] = "fr"
        payload["store_settings"]["timezone"] = "Europe/Paris"
        self._prepare_draft_ready_state(store, current_draft=payload)

        apply_current_ai_draft_store_core(store.id, self.user, 101)

        settings.refresh_from_db()
        self.assertEqual(settings.currency, "EUR")
        self.assertEqual(settings.language, "fr")
        self.assertEqual(settings.timezone, "Europe/Paris")
        self.assertEqual(settings.store_email, "support@example.com")
        self.assertEqual(settings.store_phone, "+963999999999")
        self.assertFalse(settings.email_notifications)
        self.assertFalse(settings.order_notifications)
        self.assertTrue(settings.marketing_notifications)
        self.assertTrue(settings.two_factor_auth)

    def test_store_settings_selector_is_tenant_and_owner_safe(self):
        store = self._create_store()
        self._seed_templates()
        other_owner_same_tenant = User.objects.create_user(
            username="settings_other_owner",
            email="settings_other_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        other_owner_same_tenant.is_active = True
        other_owner_same_tenant.tenant_id = 101
        other_owner_same_tenant.save(update_fields=["is_active", "tenant_id"])
        other_store = Store.objects.create(
            owner=other_owner_same_tenant,
            tenant_id=101,
            name="Other Owner Store",
            description="",
            status="draft",
        )
        other_settings = StoreSettings.objects.create(
            store=other_store,
            currency="GBP",
            language="en",
            timezone="Europe/London",
        )

        other_tenant_owner = User.objects.create_user(
            username="settings_other_tenant",
            email="settings_other_tenant@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        other_tenant_owner.is_active = True
        other_tenant_owner.tenant_id = 202
        other_tenant_owner.save(update_fields=["is_active", "tenant_id"])
        other_tenant_store = Store.objects.create(
            owner=other_tenant_owner,
            tenant_id=202,
            name="Other Tenant Store",
            description="",
            status="draft",
        )
        other_tenant_settings = StoreSettings.objects.create(
            store=other_tenant_store,
            currency="CAD",
            language="fr",
            timezone="America/Toronto",
        )

        self.assertIsNone(
            get_store_settings_for_ai_flow(
                store_id=other_store.id,
                user=self.user,
                tenant_id=101,
            )
        )
        self.assertIsNone(
            get_store_settings_for_ai_flow(
                store_id=other_tenant_store.id,
                user=other_tenant_owner,
                tenant_id=101,
            )
        )

        payload = self._valid_full_draft_payload()
        payload["store_settings"]["currency"] = "SYP"
        payload["store_settings"]["language"] = "ar"
        payload["store_settings"]["timezone"] = "Asia/Damascus"
        self._prepare_draft_ready_state(store, current_draft=payload)

        apply_current_ai_draft_store_core(store.id, self.user, 101)

        other_settings.refresh_from_db()
        other_tenant_settings.refresh_from_db()
        self.assertEqual(other_settings.currency, "GBP")
        self.assertEqual(other_settings.language, "en")
        self.assertEqual(other_settings.timezone, "Europe/London")
        self.assertEqual(other_tenant_settings.currency, "CAD")
        self.assertEqual(other_tenant_settings.language, "fr")
        self.assertEqual(other_tenant_settings.timezone, "America/Toronto")

    def test_apply_current_ai_draft_store_core_invalid_store_settings_fails_before_persistence(self):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Should Not Persist"
        payload["store_settings"]["currency"] = ""
        self._prepare_draft_ready_state(store, current_draft=payload)

        with self.assertRaises(ValidationError):
            apply_current_ai_draft_store_core(store.id, self.user, 101)

        store.refresh_from_db()
        self.assertEqual(store.name, "AI Draft Store")
        self.assertFalse(StoreSettings.objects.filter(store=store).exists())
        self.assertFalse(StoreThemeConfig.objects.filter(store=store).exists())

    def test_apply_current_ai_draft_store_core_hides_raw_database_exception(self):
        store = self._create_store()
        self._seed_templates()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Should Roll Back"
        payload["store"]["description"] = "Should roll back"
        self._prepare_draft_ready_state(store, current_draft=payload)
        raw_reason = "OperationalError: no such column: themes_storethemeconfig.primary_color"

        with patch("AI_Store_Creation_Service.apply_services.logger.warning") as mock_warning:
            with patch(
                "AI_Store_Creation_Service.apply_services.StoreThemeConfig.objects.create",
                side_effect=Exception(raw_reason),
            ):
                with self.assertRaises(ValidationError) as ctx:
                    apply_current_ai_draft_store_core(store.id, self.user, 101)

        public_error = str(ctx.exception)
        self.assertIn(STORE_CORE_APPLY_FAILED_USER_MESSAGE, public_error)
        self.assertNotIn("OperationalError", public_error)
        self.assertNotIn("themes_storethemeconfig", public_error)
        self.assertIsNotNone(ctx.exception.__cause__)
        self.assertIn(raw_reason, str(ctx.exception.__cause__))
        self.assertIn(raw_reason, str(mock_warning.call_args))

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="apply_store_core",
            status="failed",
        ).latest("id")
        self.assertIn(raw_reason, audit.message)

        store.refresh_from_db()
        self.assertEqual(store.name, "AI Draft Store")
        self.assertEqual(store.description, "")
        self.assertFalse(StoreSettings.objects.filter(store=store).exists())
        self.assertFalse(StoreThemeConfig.objects.filter(store=store).exists())

    def test_apply_current_ai_draft_categories_success(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_categories(store.id, self.user, 101)

        self.assertEqual(Category.objects.filter(store=store).count(), 2)
        self.assertEqual(result["created_categories"], ["Clothes", "Shoes"])
        self.assertEqual(result["skipped_categories"], [])

    def test_apply_current_ai_draft_categories_hides_raw_database_exception(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=payload)
        raw_reason = "UNIQUE constraint failed: categories_category.name"

        with patch("AI_Store_Creation_Service.apply_services.logger.warning") as mock_warning:
            with patch(
                "AI_Store_Creation_Service.apply_services.Category.objects.create",
                side_effect=Exception(raw_reason),
            ):
                with self.assertRaises(ValidationError) as ctx:
                    apply_current_ai_draft_categories(store.id, self.user, 101)

        public_error = str(ctx.exception)
        self.assertIn(CATEGORY_APPLY_FAILED_USER_MESSAGE, public_error)
        self.assertNotIn("UNIQUE", public_error)
        self.assertNotIn("categories_category", public_error)
        self.assertIsNotNone(ctx.exception.__cause__)
        self.assertIn(raw_reason, str(ctx.exception.__cause__))
        self.assertIn(raw_reason, str(mock_warning.call_args))
        self.assertEqual(Category.objects.filter(store=store).count(), 0)

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="apply_categories",
            status="failed",
        ).latest("id")
        self.assertIn(raw_reason, audit.message)

    def test_apply_current_ai_draft_products_success(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")

        payload = self._valid_full_draft_payload()
        payload["products"][0]["sku"] = "TS-NEW-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][0]["image_url"] = "https://img.example.com/ts-001.jpg"
        payload["products"][1]["sku"] = "SN-NEW-001"
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][1]["image_url"] = ""
        self._prepare_draft_ready_state(store, current_draft=payload)

        result = apply_current_ai_draft_products(store.id, self.user, 101)

        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 1)
        self.assertEqual(result["created_products"], ["TS-NEW-001", "SN-NEW-001"])
        self.assertEqual(result["skipped_products"], [])

    def test_apply_current_ai_draft_products_hides_raw_database_exception(self):
        store = self._create_store()
        Category.objects.create(store=store, tenant_id=101, name="Clothes")
        Category.objects.create(store=store, tenant_id=101, name="Shoes")
        payload = self._valid_full_draft_payload()
        self._prepare_draft_ready_state(store, current_draft=payload)
        raw_reason = "UNIQUE constraint failed: products_product.sku"

        with patch("AI_Store_Creation_Service.apply_services.logger.warning") as mock_warning:
            with patch(
                "AI_Store_Creation_Service.apply_services.Product.objects.create",
                side_effect=Exception(raw_reason),
            ):
                with self.assertRaises(ValidationError) as ctx:
                    apply_current_ai_draft_products(store.id, self.user, 101)

        public_error = str(ctx.exception)
        self.assertIn(PRODUCT_APPLY_FAILED_USER_MESSAGE, public_error)
        self.assertNotIn("UNIQUE", public_error)
        self.assertNotIn("products_product", public_error)
        self.assertIsNotNone(ctx.exception.__cause__)
        self.assertIn(raw_reason, str(ctx.exception.__cause__))
        self.assertIn(raw_reason, str(mock_warning.call_args))
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 0)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 0)

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="apply_products",
            status="failed",
        ).latest("id")
        self.assertIn(raw_reason, audit.message)

    def test_apply_current_ai_draft_to_store_success(self):
        store = self._create_store()
        self._seed_templates()

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Final Applied Store"
        payload["store"]["description"] = "Final applied description"
        payload["store_settings"]["currency"] = "EUR"
        payload["store_settings"]["language"] = "fr"
        payload["store_settings"]["timezone"] = "Europe/Paris"
        payload["products"][0]["sku"] = "AP-TS-001"
        payload["products"][1]["sku"] = "AP-SN-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][0]["image_url"] = "https://img.example.com/ap-ts-001.jpg"
        payload["products"][1]["image_url"] = ""
        self._prepare_draft_ready_state(store, current_draft=payload)

        with self.captureOnCommitCallbacks(execute=True):
            result = apply_current_ai_draft_to_store(store.id, self.user, 101)

        store.refresh_from_db()
        settings = StoreSettings.objects.get(store=store)
        self.assertEqual(store.status, "setup")
        self.assertEqual(settings.currency, "EUR")
        self.assertEqual(settings.language, "fr")
        self.assertEqual(settings.timezone, "Europe/Paris")
        self.assertEqual(StoreThemeConfig.objects.filter(store=store).count(), 1)
        self.assertEqual(Category.objects.filter(store=store).count(), 2)
        self.assertEqual(Product.objects.filter(store=store).count(), 2)
        self.assertEqual(Inventory.objects.filter(product__store=store).count(), 2)
        self.assertEqual(ProductImage.objects.filter(product__store=store).count(), 1)
        self.assertIsNone(get_ai_draft(store.id))
        self.assertIsNone(get_ai_draft_meta(store.id))

        self.assertEqual(result["store_id"], store.id)
        self.assertEqual(result["workflow_status"], WORKFLOW_STATUS_APPLIED)
        self.assertEqual(result["store_status"], "setup")
        self.assertNotIn("final_status", result)
        self.assertTrue(result["store_core_applied"])
        self.assertTrue(result["draft_cleanup_scheduled"])

    def test_apply_current_ai_draft_to_store_rolls_back_settings_theme_and_status_on_later_failure(self):
        store = self._create_store()
        self._seed_templates()
        original_name = store.name
        original_description = store.description

        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Rolled Back Store"
        payload["store"]["description"] = "Rolled back description"
        payload["store_settings"]["currency"] = "EUR"
        payload["store_settings"]["language"] = "fr"
        payload["store_settings"]["timezone"] = "Europe/Paris"
        self._prepare_draft_ready_state(store, current_draft=payload)
        raw_reason = "UNIQUE constraint failed: products_product.sku"

        with patch(
            "AI_Store_Creation_Service.apply_services.Product.objects.create",
            side_effect=Exception(raw_reason),
        ):
            with self.assertRaises(ValidationError) as ctx:
                apply_current_ai_draft_to_store(store.id, self.user, 101)

        public_error = str(ctx.exception)
        self.assertIn(PRODUCT_APPLY_FAILED_USER_MESSAGE, public_error)
        self.assertNotIn("UNIQUE", public_error)
        self.assertNotIn("products_product", public_error)
        self.assertNotIn(raw_reason, public_error)

        store.refresh_from_db()
        self.assertEqual(store.name, original_name)
        self.assertEqual(store.description, original_description)
        self.assertEqual(store.status, "draft")
        self.assertFalse(StoreSettings.objects.filter(store=store).exists())
        self.assertFalse(StoreThemeConfig.objects.filter(store=store).exists())
        self.assertEqual(Category.objects.filter(store=store).count(), 0)
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertIsNotNone(get_ai_draft(store.id))
        self.assertIsNotNone(get_ai_draft_meta(store.id))

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="apply_draft",
            status="failed",
        ).latest("id")
        self.assertIn(raw_reason, audit.message)

    def test_apply_current_ai_draft_to_store_rejects_non_ready_without_applied_status(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "original_user_store_description": "Sportswear store",
            },
        )

        with self.assertRaises(ValidationError):
            apply_current_ai_draft_to_store(store.id, self.user, 101)

        store.refresh_from_db()
        self.assertEqual(store.status, "draft")
        self.assertIsNotNone(get_ai_draft(store.id))


class AICreationApiTests(AIWorkflowBaseMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="ai_api_owner",
            email="ai_api_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.user.is_active = True
        self.user.tenant_id = 101
        self.user.save(update_fields=["is_active", "tenant_id"])

        self.other_owner_same_tenant = User.objects.create_user(
            username="ai_api_other_owner",
            email="ai_api_other_owner@example.com",
            password="StrongPass123!",
            role="Store Owner",
        )
        self.other_owner_same_tenant.is_active = True
        self.other_owner_same_tenant.tenant_id = 101
        self.other_owner_same_tenant.save(update_fields=["is_active", "tenant_id"])

        self._seed_templates()
        self._authenticate(self.user)

    def _seed_templates(self):
        ThemeTemplate.objects.create(name="Modern", description="Modern template")
        ThemeTemplate.objects.create(name="Classic", description="Classic template")

    def _authenticate(self, user):
        response = self.client.post(
            "/api/auth/login/",
            {"email": user.email, "password": "StrongPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")

    @staticmethod
    def _payload(response):
        return response.json()

    def _create_store(self, owner=None, tenant_id=None) -> Store:
        owner = owner or self.user
        tenant_id = tenant_id if tenant_id is not None else owner.tenant_id
        return Store.objects.create(
            owner=owner,
            tenant_id=tenant_id,
            name="Endpoint Draft Store",
            description="",
            status="draft",
        )

    def test_start_endpoint_happy_path(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": "A modern sportswear store for athletes",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {"store_id", "draft_payload", "draft_metadata"})
        self.assertEqual(body["draft_payload"], payload)
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)

        created_store = Store.objects.get(id=body["store_id"])
        self.assertTrue(created_store.name.strip())

    def test_start_endpoint_missing_templates_returns_recoverable_state_with_store_id(self):
        ThemeTemplate.objects.all().delete()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": "I want to build a modern skincare products store.",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        mock_get_provider.assert_not_called()
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {"store_id", "draft_payload", "draft_metadata"})
        self.assertIsInstance(body["store_id"], int)

        store = Store.objects.get(id=body["store_id"])
        self.assertEqual(store.owner_id, self.user.id)
        self.assertEqual(store.tenant_id, 101)
        self.assertEqual(store.status, "draft")

        payload = body["draft_payload"]
        metadata = body["draft_metadata"]
        self.assertFalse(payload["clarification_needed"])
        self.assertEqual(payload["clarification_questions"], [])
        self.assertEqual(payload["error_code"], THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE)
        self.assertEqual(payload["user_message"], THEME_TEMPLATES_UNAVAILABLE_USER_MESSAGE)
        self.assertTrue(payload["retry_allowed"])
        self.assertTrue(payload["manual_edit_allowed"])
        self.assertEqual(metadata["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(metadata["is_fallback"])
        self.assertEqual(metadata["error_code"], THEME_TEMPLATES_UNAVAILABLE_ERROR_CODE)
        self.assertEqual(metadata["clarification_round_count"], 0)
        self.assertEqual(metadata["repair_attempt_count"], 0)
        self.assertEqual(metadata["max_clarification_rounds"], MAX_CLARIFICATION_ROUNDS)
        self.assertEqual(metadata["max_repair_attempts"], MAX_REPAIR_ATTEMPTS)

        serialized_body = json.dumps(body)
        self.assertNotIn("No available theme templates found", serialized_body)
        self.assertNotIn("Traceback", serialized_body)

        current_response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id}),
            format="json",
        )
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(self._payload(current_response), body)

        self._authenticate(self.other_owner_same_tenant)
        forbidden_response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id}),
            format="json",
        )
        self.assertEqual(forbidden_response.status_code, 404)

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="start_draft",
            status="failed",
        ).latest("id")
        self.assertIn("No available theme templates found", audit.message)

    def test_start_endpoint_accepts_deprecated_user_store_description(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_store_description": "A modern sportswear store for athletes",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {"store_id", "draft_payload", "draft_metadata"})

    def test_start_endpoint_prefers_user_description_when_both_fields_exist(self):
        payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(payload)

            response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": 'store name is "Priority Name"',
                    "user_store_description": 'store name is "Deprecated Name"',
                },
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        store_id = self._payload(response)["store_id"]
        created_store = Store.objects.get(id=store_id)
        self.assertEqual(created_store.name, "Priority Name")

    def test_current_draft_endpoint_happy_path(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        metadata = {
            "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
            "current_step": "setting_up_store_configuration",
            "mode": "draft_ready",
            "original_user_store_description": "Sportswear store",
        }
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(store.id, metadata)

        response = self.client.get(reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id}))

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["store_id"], store.id)
        self.assertEqual(body["draft_payload"], payload)
        self.assertEqual(
            body["draft_metadata"],
            {
                **metadata,
                "clarification_round_count": 0,
                "repair_attempt_count": 0,
                "max_clarification_rounds": MAX_CLARIFICATION_ROUNDS,
                "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                "is_fallback": False,
                "clarification_history": [],
            },
        )

    def test_clarification_endpoint_happy_path(self):
        start_payload = self._clarification_payload()
        final_payload = self._valid_full_draft_payload()

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(start_payload)

            start_response = self.client.post(
                reverse("ai_store_creation:start-draft"),
                {
                    "user_description": "I need help defining my store",
                },
                format="json",
            )
            self.assertEqual(start_response.status_code, 201)
            store_id = start_response.json()["store_id"]

            mock_get_provider.return_value.clarify_store_draft.return_value = self._as_provider_response(final_payload)
            response = self.client.post(
                reverse("ai_store_creation:clarify-draft", kwargs={"store_id": store_id}),
                {"clarification_answers": {"store_type": "Fashion"}},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["store_id"], store_id)
        self.assertEqual(body["draft_payload"], final_payload)
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)

    def test_regenerate_endpoint_happy_path(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Target audience: adults",
                "clarification_history": [{"round": 1, "clarification_input": "Target audience: adults"}],
            },
        )

        regenerated = self._valid_full_draft_payload()
        regenerated["store"]["name"] = "Regenerated Store Name"

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.regenerate_store_draft.return_value = self._as_provider_response(regenerated)
            response = self.client.post(
                reverse("ai_store_creation:regenerate-draft", kwargs={"store_id": store.id}),
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["draft_payload"]["store"]["name"], "Regenerated Store Name")
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)

    def test_regenerate_section_endpoint_happy_path(self):
        store = self._create_store()
        base_payload = self._valid_full_draft_payload()
        save_ai_draft(store.id, base_payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Prefer modern style",
                "clarification_history": [{"round": 1, "clarification_input": "Prefer modern style"}],
            },
        )

        replacement_theme = {
            "theme_template": "Classic",
            "primary_color": "#101010",
            "secondary_color": "rgb(255, 255, 255)",
            "font_family": "Inter",
            "logo_url": "",
            "banner_url": "",
        }

        with patch("AI_Store_Creation_Service.services.get_ai_provider_client") as mock_get_provider:
            mock_get_provider.return_value.regenerate_store_draft_section.return_value = self._as_provider_response(
                {"theme": replacement_theme}
            )
            response = self.client.post(
                reverse("ai_store_creation:regenerate-draft-section", kwargs={"store_id": store.id}),
                {"target_section": "theme"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(body["draft_payload"]["theme"], replacement_theme)
        self.assertEqual(body["draft_payload"]["categories"], base_payload["categories"])
        self.assertEqual(body["draft_payload"]["products"], base_payload["products"])
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_READY_FOR_REVIEW)

    def test_apply_endpoint_happy_path(self):
        store = self._create_store()
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Final Applied Store"
        payload["store"]["description"] = "Final applied description"
        payload["products"][0]["sku"] = "AP-TS-001"
        payload["products"][1]["sku"] = "AP-SN-001"
        payload["products"][0]["stock_quantity"] = 9
        payload["products"][1]["stock_quantity"] = 4
        payload["products"][0]["image_url"] = "https://img.example.com/ap-ts-001.jpg"
        payload["products"][1]["image_url"] = ""
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Prefer modern style",
                "clarification_history": [{"round": 1, "clarification_input": "Prefer modern style"}],
            },
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("ai_store_creation:apply-draft", kwargs={"store_id": store.id}),
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = self._payload(response)
        self.assertEqual(set(body.keys()), {
            "store_id",
            "workflow_status",
            "store_status",
            "store_core_applied",
            "categories",
            "products",
            "draft_cleanup_scheduled",
        })
        self.assertEqual(body["workflow_status"], WORKFLOW_STATUS_APPLIED)
        self.assertEqual(body["store_status"], "setup")
        self.assertNotIn("final_status", body)
        self.assertTrue(body["draft_cleanup_scheduled"])

        store.refresh_from_db()
        self.assertEqual(store.status, "setup")
        self.assertIsNone(get_ai_draft(store.id))
        self.assertIsNone(get_ai_draft_meta(store.id))

    def test_apply_endpoint_hides_raw_product_apply_failure_and_preserves_draft(self):
        store = self._create_store()
        original_name = store.name
        original_description = store.description
        payload = self._valid_full_draft_payload()
        payload["store"]["name"] = "Should Not Apply"
        payload["store"]["description"] = "Should not apply"
        payload["store_settings"]["currency"] = "EUR"
        payload["store_settings"]["language"] = "fr"
        payload["store_settings"]["timezone"] = "Europe/Paris"
        save_ai_draft(store.id, payload)
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
                "latest_clarification_input": "Prefer modern style",
                "clarification_history": [{"round": 1, "clarification_input": "Prefer modern style"}],
            },
        )
        raw_reason = "UNIQUE constraint failed: products_product.sku"

        with patch(
            "AI_Store_Creation_Service.apply_services.Product.objects.create",
            side_effect=Exception(raw_reason),
        ):
            response = self.client.post(
                reverse("ai_store_creation:apply-draft", kwargs={"store_id": store.id}),
                {},
                format="json",
            )

        self.assertEqual(response.status_code, 400)
        body = self._payload(response)
        self.assertEqual(body["detail"], PRODUCT_APPLY_FAILED_USER_MESSAGE)
        self.assertNotIn("workflow_status", body)
        serialized_body = json.dumps(body)
        self.assertNotIn("UNIQUE", serialized_body)
        self.assertNotIn("products_product", serialized_body)
        self.assertNotIn("constraint", serialized_body.lower())
        self.assertNotIn(raw_reason, serialized_body)

        store.refresh_from_db()
        self.assertEqual(store.name, original_name)
        self.assertEqual(store.description, original_description)
        self.assertEqual(store.status, "draft")
        self.assertFalse(StoreSettings.objects.filter(store=store).exists())
        self.assertFalse(StoreThemeConfig.objects.filter(store=store).exists())
        self.assertEqual(Category.objects.filter(store=store).count(), 0)
        self.assertEqual(Product.objects.filter(store=store).count(), 0)
        self.assertIsNotNone(get_ai_draft(store.id))
        self.assertIsNotNone(get_ai_draft_meta(store.id))

        audit = AIStoreAuditLog.objects.filter(
            store_id=store.id,
            action="apply_draft",
            status="failed",
        ).latest("id")
        self.assertIn(raw_reason, audit.message)

    def test_apply_endpoint_non_ready_draft_does_not_return_applied(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "original_user_store_description": "Original idea",
            },
        )

        response = self.client.post(
            reverse("ai_store_creation:apply-draft", kwargs={"store_id": store.id}),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        body = self._payload(response)
        self.assertNotIn("workflow_status", body)
        self.assertIn("detail", body)
        store.refresh_from_db()
        self.assertEqual(store.status, "draft")

    def test_start_endpoint_rejects_unauthenticated(self):
        self.client.credentials()
        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "A valid store description for provider failure"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_start_endpoint_rejects_blank_description(self):
        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "   ", "user_store_description": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_endpoint_rejects_short_description_before_store_or_provider(
        self,
        mock_get_provider,
    ):
        initial_store_count = Store.objects.count()

        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "too short"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("at least 5 words", str(response.json()))
        self.assertEqual(Store.objects.count(), initial_store_count)
        mock_get_provider.assert_not_called()

    def test_current_draft_rejects_wrong_owner_access(self):
        foreign_store = self._create_store(owner=self.other_owner_same_tenant, tenant_id=101)
        save_ai_draft(foreign_store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            foreign_store.id,
            {
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "original_user_store_description": "Desc",
            },
        )

        response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": foreign_store.id})
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_current_draft_returns_404_when_missing(self):
        store = self._create_store()
        response = self.client.get(
            reverse("ai_store_creation:current-draft", kwargs={"store_id": store.id})
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.json())

    def test_clarification_rejects_blank_answers(self):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 0,
                "original_user_store_description": "Original store description",
            },
        )

        response = self.client.post(
            reverse("ai_store_creation:clarify-draft", kwargs={"store_id": store.id}),
            {"clarification_answers": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_regenerate_section_rejects_invalid_target_section(self):
        store = self._create_store()
        save_ai_draft(store.id, self._valid_full_draft_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_READY_FOR_REVIEW,
                "current_step": "setting_up_store_configuration",
                "mode": "draft_ready",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
            },
        )

        response = self.client.post(
            reverse("ai_store_creation:regenerate-draft-section", kwargs={"store_id": store.id}),
            {"target_section": "store"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_endpoint_returns_safe_fallback_when_provider_fails(self, mock_get_provider):
        mock_get_provider.return_value.generate_store_draft.side_effect = RuntimeError("provider timeout")

        response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "A valid store description for provider failure"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(body["draft_metadata"]["is_fallback"])
        self.assertFalse(body["draft_payload"]["clarification_needed"])
        self.assertEqual(body["draft_payload"]["clarification_questions"], [])
        self.assertEqual(body["draft_payload"]["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertEqual(body["draft_payload"]["user_message"], RECOVERABLE_FAILURE_USER_MESSAGE)
        self.assertNotIn("provider timeout", body["draft_payload"]["user_message"])

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_start_endpoint_repeated_vague_descriptions_create_valid_unique_stores(
        self,
        mock_get_provider,
    ):
        mock_get_provider.return_value.generate_store_draft.return_value = self._as_provider_response(
            self._clarification_payload()
        )

        first_response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Please create a simple online store"},
            format="json",
        )
        second_response = self.client.post(
            reverse("ai_store_creation:start-draft"),
            {"user_description": "Please create a simple online store"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        first_store = Store.objects.get(id=self._payload(first_response)["store_id"])
        second_store = Store.objects.get(id=self._payload(second_response)["store_id"])
        self.assertTrue(first_store.name.strip())
        self.assertTrue(second_store.name.strip())
        self.assertNotEqual(first_store.slug, second_store.slug)

    @patch("AI_Store_Creation_Service.services.get_ai_provider_client")
    def test_regenerate_endpoint_returns_safe_fallback_when_provider_fails(self, mock_get_provider):
        store = self._create_store()
        save_ai_draft(store.id, self._clarification_payload())
        save_ai_draft_meta(
            store.id,
            {
                "status": WORKFLOW_STATUS_NEEDS_CLARIFICATION,
                "current_step": "analyzing_description",
                "mode": "clarification",
                "is_fallback": False,
                "clarification_round_count": 1,
                "original_user_store_description": "Original idea",
            },
        )

        mock_get_provider.return_value.regenerate_store_draft.side_effect = RuntimeError("provider timeout")

        response = self.client.post(
            reverse("ai_store_creation:regenerate-draft", kwargs={"store_id": store.id}),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["draft_metadata"]["status"], WORKFLOW_STATUS_FAILED_RECOVERABLE)
        self.assertTrue(body["draft_metadata"]["is_fallback"])
        self.assertFalse(body["draft_payload"]["clarification_needed"])
        self.assertEqual(body["draft_payload"]["clarification_questions"], [])
        self.assertEqual(body["draft_payload"]["error_code"], RECOVERABLE_FAILURE_ERROR_CODE)
        self.assertNotIn("provider timeout", body["draft_payload"]["user_message"])
