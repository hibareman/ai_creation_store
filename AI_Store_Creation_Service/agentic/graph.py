"""Simple LangGraph orchestration for AI-assisted store creation."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    apply_store_node,
    blueprint_node,
    clarify_node,
    decide_node,
    generate_node,
    feedback_node,
    human_review_node,
    merge_answers_node,
    repair_node,
    recoverable_failure_node,
    understand_node,
    validate_node,
)
from .routing import (
    route_after_blueprint,
    route_after_clarify,
    route_after_decide,
    route_after_generate,
    route_after_merge,
    route_after_repair,
    route_after_validate,
    route_workflow_entry,
)
from .state import AIStoreAgentState


def build_agentic_graph() -> StateGraph:
    """Build the minimal supported workflow.

    Understand -> Feedback -> Clarify/Generate -> Structural Validate -> Human Review.
    """
    graph = StateGraph(AIStoreAgentState)
    graph.add_node("apply_store", apply_store_node)
    graph.add_node("understand", understand_node)
    graph.add_node("merge_answers", merge_answers_node)
    graph.add_node("feedback", feedback_node)
    graph.add_node("decide", decide_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("blueprint", blueprint_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("repair", repair_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("recoverable_failure", recoverable_failure_node)

    graph.add_conditional_edges(
        START,
        route_workflow_entry,
        {
            "understand": "understand",
            "merge_answers": "merge_answers",
            "apply_store": "apply_store",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_conditional_edges(
        "merge_answers",
        route_after_merge,
        {
            "understand": "understand",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_edge("understand", "feedback")
    graph.add_edge("feedback", "decide")
    graph.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "clarify": "clarify",
            "generate": "blueprint",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_conditional_edges(
        "clarify",
        route_after_clarify,
        {
            "human_review": "human_review",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_conditional_edges("blueprint", route_after_blueprint, {"generate":"generate", "failed_recoverable":"recoverable_failure"})
    graph.add_conditional_edges(
        "generate",
        route_after_generate,
        {"validate": "validate", "failed_recoverable": "recoverable_failure"},
    )
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "human_review": "human_review",
            "repair": "repair",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_conditional_edges(
        "repair",
        route_after_repair,
        {"validate": "validate", "failed_recoverable": "recoverable_failure"},
    )
    graph.add_edge("human_review", END)
    graph.add_edge("apply_store", END)
    graph.add_edge("recoverable_failure", END)
    return graph


def compile_agentic_graph():
    return build_agentic_graph().compile()


__all__ = ["build_agentic_graph", "compile_agentic_graph"]
