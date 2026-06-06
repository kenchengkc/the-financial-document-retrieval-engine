from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    rewritten_queries: list[str]
    filters: dict[str, Any]
    route: list[str]
    text_candidates: list[dict[str, Any]]
    table_candidates: list[dict[str, Any]]
    retrieved_candidates: list[dict[str, Any]]
    reranked_candidates: list[dict[str, Any]]
    retrieval_gate: dict[str, Any]
    financial_facts: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    answer: dict[str, Any] | None
    citations: list[dict[str, Any]]
    errors: list[str]
    should_abstain: bool
    abstention_reason: str | None
    trace: list[dict[str, Any]]
