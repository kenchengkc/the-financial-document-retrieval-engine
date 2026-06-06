from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from fdre.graph.nodes import (
    WorkflowContext,
    evaluate_retrieval_gate_node,
    finalize_or_abstain_node,
    generate_answer_node,
    merge_candidates_node,
    preprocess_query_node,
    rerank_node,
    retrieve_financial_facts_node,
    retrieve_tables_node,
    retrieve_text_node,
    route_tools_node,
    verify_citations_node,
)
from fdre.graph.state import AgentState


def build_answer_workflow(context: WorkflowContext) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node(
        "preprocess_query",
        lambda state: preprocess_query_node(context, state),
    )
    graph.add_node("route_tools", lambda state: route_tools_node(context, state))
    graph.add_node("retrieve_text", lambda state: retrieve_text_node(context, state))
    graph.add_node("retrieve_tables", lambda state: retrieve_tables_node(context, state))
    graph.add_node(
        "retrieve_financial_facts",
        lambda state: retrieve_financial_facts_node(context, state),
    )
    graph.add_node(
        "merge_candidates",
        lambda state: merge_candidates_node(context, state),
    )
    graph.add_node("rerank", lambda state: rerank_node(context, state))
    graph.add_node(
        "evaluate_retrieval_gate",
        lambda state: evaluate_retrieval_gate_node(context, state),
    )
    graph.add_node(
        "generate_answer",
        lambda state: generate_answer_node(context, state),
    )
    graph.add_node(
        "verify_citations",
        lambda state: verify_citations_node(context, state),
    )
    graph.add_node(
        "finalize_or_abstain",
        lambda state: finalize_or_abstain_node(context, state),
    )

    graph.add_edge(START, "preprocess_query")
    graph.add_edge("preprocess_query", "route_tools")
    graph.add_edge("route_tools", "retrieve_text")
    graph.add_edge("retrieve_text", "retrieve_tables")
    graph.add_edge("retrieve_tables", "retrieve_financial_facts")
    graph.add_edge("retrieve_financial_facts", "merge_candidates")
    graph.add_edge("merge_candidates", "rerank")
    graph.add_edge("rerank", "evaluate_retrieval_gate")
    graph.add_conditional_edges(
        "evaluate_retrieval_gate",
        lambda state: (
            "finalize_or_abstain" if state.get("should_abstain") else "generate_answer"
        ),
        {
            "generate_answer": "generate_answer",
            "finalize_or_abstain": "finalize_or_abstain",
        },
    )
    graph.add_edge("generate_answer", "verify_citations")
    graph.add_edge("verify_citations", "finalize_or_abstain")
    graph.add_edge("finalize_or_abstain", END)
    return graph.compile()


def run_answer_workflow(context: WorkflowContext, question: str) -> AgentState:
    initial: AgentState = {
        "user_query": question,
        "errors": [],
        "citations": [],
        "trace": [],
        "should_abstain": False,
        "abstention_reason": None,
    }
    return cast(AgentState, build_answer_workflow(context).invoke(initial))
