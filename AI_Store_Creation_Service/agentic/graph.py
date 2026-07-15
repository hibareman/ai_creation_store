"""LangGraph skeleton for the future agentic AI Store Creation workflow."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
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
from .routing import (
    route_after_decide,
    route_after_generate,
    route_after_merge,
    route_after_repair,
    route_after_validate,
    route_workflow_entry,
)
from .state import AIStoreAgentState


def build_agentic_graph() -> StateGraph:
    graph = StateGraph(AIStoreAgentState)

    graph.add_node("understand", understand_node)
    graph.add_node("merge_answers", merge_answers_node)
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
    graph.add_edge("understand", "decide")
    graph.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "clarify": "clarify",
            "blueprint": "blueprint",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_edge("clarify", "human_review")
    graph.add_edge("blueprint", "generate")
    graph.add_conditional_edges(
        "generate",
        route_after_generate,
        {
            "validate": "validate",
            "failed_recoverable": "recoverable_failure",
        },
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
        {
            "validate": "validate",
            "failed_recoverable": "recoverable_failure",
        },
    )
    graph.add_edge("human_review", END)
    graph.add_edge("recoverable_failure", END)

    return graph


def compile_agentic_graph():
    return build_agentic_graph().compile()


__all__ = ["build_agentic_graph", "compile_agentic_graph"]
