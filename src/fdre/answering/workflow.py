from __future__ import annotations

from dataclasses import dataclass

from .nodes import (
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
from .state import AnswerWorkflowState


@dataclass(frozen=True, slots=True)
class AnswerWorkflow:
    """Deterministic answer pipeline with the same invoke contract as the former graph."""

    context: WorkflowContext

    def invoke(self, initial: AnswerWorkflowState) -> AnswerWorkflowState:
        state = initial.copy()

        state.update(preprocess_query_node(self.context, state))
        state.update(route_tools_node(self.context, state))
        state.update(retrieve_text_node(self.context, state))
        state.update(retrieve_tables_node(self.context, state))
        state.update(retrieve_financial_facts_node(self.context, state))
        state.update(merge_candidates_node(self.context, state))
        state.update(rerank_node(self.context, state))
        state.update(evaluate_retrieval_gate_node(self.context, state))

        if not state.get("should_abstain", False):
            state.update(generate_answer_node(self.context, state))
            state.update(verify_citations_node(self.context, state))

        state.update(finalize_or_abstain_node(self.context, state))
        return state


def build_answer_workflow(context: WorkflowContext) -> AnswerWorkflow:
    """Build the lightweight deterministic workflow wrapper."""

    return AnswerWorkflow(context)


def run_answer_workflow(context: WorkflowContext, question: str) -> AnswerWorkflowState:
    initial: AnswerWorkflowState = {
        "user_query": question,
        "errors": [],
        "citations": [],
        "trace": [],
        "should_abstain": False,
        "abstention_reason": None,
    }
    return build_answer_workflow(context).invoke(initial)
