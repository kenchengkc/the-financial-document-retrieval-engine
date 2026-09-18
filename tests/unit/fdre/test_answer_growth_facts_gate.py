from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from fdre.answering.nodes import (
    ExtractiveAnswerGenerator,
    WorkflowContext,
    evaluate_retrieval_gate_node,
)
from fdre.answering.state import AnswerWorkflowState
from fdre.citations.verifier import CitationVerifier
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


def _evaluate_without_financial_facts(question: str) -> AnswerWorkflowState:
    candidate = RetrievalCandidate(
        chunk_id=1,
        text="Management described a growth strategy built on selective acquisitions.",
        metadata={"ticker": "AAPL", "element_type": "text"},
        rerank_score=0.9,
    )
    state: AnswerWorkflowState = {
        "user_query": question,
        "route": ["text", "financial_facts"],
        "financial_facts": [],
        "reranked_candidates": [candidate.model_dump(mode="json")],
    }

    with Session(create_engine("sqlite+pysqlite:///:memory:")) as session:
        context = WorkflowContext(
            session=session,
            settings=Settings(
                EMBEDDING_PROVIDER="local_hash",
                EMBEDDING_MODEL="local-hash-v1",
                RERANKER_PROVIDER="fake",
                MIN_EVIDENCE_CHUNKS=1,
                MIN_RETRIEVAL_SCORE=0,
                NEIGHBOR_EXPANSION_WINDOW=0,
            ),
            generator=ExtractiveAnswerGenerator(),
            verifier=CitationVerifier(),
        )
        return evaluate_retrieval_gate_node(context, state)


def test_narrative_growth_does_not_require_structured_financial_facts() -> None:
    result = _evaluate_without_financial_facts(
        "What growth strategy did Apple describe around acquisitions?"
    )

    assert result["should_abstain"] is False
    assert result["abstention_reason"] is None


def test_revenue_growth_still_requires_structured_financial_facts() -> None:
    result = _evaluate_without_financial_facts("What was Apple's revenue growth?")

    assert result["should_abstain"] is True
    assert result["abstention_reason"] == (
        "Structured financial facts required by the question are unavailable."
    )


def test_multi_issuer_comparison_requires_fact_coverage_for_every_ticker() -> None:
    candidate = RetrievalCandidate(
        chunk_id=1,
        text="Apple and Microsoft reported results for the period.",
        metadata={"ticker": "AAPL", "element_type": "text"},
        rerank_score=0.9,
    )
    state: AnswerWorkflowState = {
        "user_query": "Compare Apple and Microsoft revenue growth.",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters(tickers=["AAPL", "MSFT"]).model_dump(mode="json"),
        "financial_facts": [{"ticker": "AAPL", "canonical_metric": "revenue"}],
        "reranked_candidates": [candidate.model_dump(mode="json")],
    }

    with Session(create_engine("sqlite+pysqlite:///:memory:")) as session:
        context = WorkflowContext(
            session=session,
            settings=Settings(
                EMBEDDING_PROVIDER="local_hash",
                EMBEDDING_MODEL="local-hash-v1",
                RERANKER_PROVIDER="fake",
                MIN_EVIDENCE_CHUNKS=1,
                MIN_RETRIEVAL_SCORE=0,
                NEIGHBOR_EXPANSION_WINDOW=0,
            ),
            generator=ExtractiveAnswerGenerator(),
            verifier=CitationVerifier(),
        )
        result = evaluate_retrieval_gate_node(context, state)

    assert result["should_abstain"] is True
    assert result["abstention_reason"] == (
        "Structured financial facts required by the question are incomplete "
        "for the requested issuers."
    )


def test_multi_issuer_comparison_passes_with_fact_coverage_for_every_ticker() -> None:
    candidate = RetrievalCandidate(
        chunk_id=1,
        text="Apple and Microsoft reported results for the period.",
        metadata={"ticker": "AAPL", "element_type": "text"},
        rerank_score=0.9,
    )
    state: AnswerWorkflowState = {
        "user_query": "Compare Apple and Microsoft revenue growth.",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters(tickers=["AAPL", "MSFT"]).model_dump(mode="json"),
        "financial_facts": [
            {"ticker": "AAPL", "canonical_metric": "revenue"},
            {"ticker": "MSFT", "canonical_metric": "revenue"},
        ],
        "reranked_candidates": [candidate.model_dump(mode="json")],
    }

    with Session(create_engine("sqlite+pysqlite:///:memory:")) as session:
        context = WorkflowContext(
            session=session,
            settings=Settings(
                EMBEDDING_PROVIDER="local_hash",
                EMBEDDING_MODEL="local-hash-v1",
                RERANKER_PROVIDER="fake",
                MIN_EVIDENCE_CHUNKS=1,
                MIN_RETRIEVAL_SCORE=0,
                NEIGHBOR_EXPANSION_WINDOW=0,
            ),
            generator=ExtractiveAnswerGenerator(),
            verifier=CitationVerifier(),
        )
        result = evaluate_retrieval_gate_node(context, state)

    assert result["should_abstain"] is False
    assert result["abstention_reason"] is None


def test_growth_query_requires_two_distinct_fact_periods() -> None:
    candidate = RetrievalCandidate(
        chunk_id=1,
        text="Apple reported revenue for the fiscal year.",
        metadata={"ticker": "AAPL", "element_type": "text"},
        rerank_score=0.9,
    )
    state: AnswerWorkflowState = {
        "user_query": "What was Apple's revenue growth?",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters(tickers=["AAPL"]).model_dump(mode="json"),
        "financial_facts": [
            {
                "ticker": "AAPL",
                "canonical_metric": "revenue",
                "period_end": "2025-12-31",
            }
        ],
        "reranked_candidates": [candidate.model_dump(mode="json")],
    }

    with Session(create_engine("sqlite+pysqlite:///:memory:")) as session:
        context = WorkflowContext(
            session=session,
            settings=Settings(
                EMBEDDING_PROVIDER="local_hash",
                EMBEDDING_MODEL="local-hash-v1",
                RERANKER_PROVIDER="fake",
                MIN_EVIDENCE_CHUNKS=1,
                MIN_RETRIEVAL_SCORE=0,
                NEIGHBOR_EXPANSION_WINDOW=0,
            ),
            generator=ExtractiveAnswerGenerator(),
            verifier=CitationVerifier(),
        )
        result = evaluate_retrieval_gate_node(context, state)

    assert result["should_abstain"] is True
    assert result["abstention_reason"] == (
        "Structured financial facts required by the question do not cover "
        "enough periods to measure growth."
    )
