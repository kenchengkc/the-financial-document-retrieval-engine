from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from fdre.answering.nodes import (
    ExtractiveAnswerGenerator,
    WorkflowContext,
    retrieve_tables_node,
)
from fdre.answering.state import AnswerWorkflowState
from fdre.citations.verifier import CitationVerifier
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


def _context() -> WorkflowContext:
    return WorkflowContext(
        session=cast(Session, object()),
        settings=Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            RERANKER_PROVIDER="fake",
        ),
        generator=ExtractiveAnswerGenerator(),
        verifier=CitationVerifier(),
    )


def _table(chunk_id: int, text: str) -> dict[str, object]:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        text=text,
        metadata={"element_type": "table", "ticker": "AAPL"},
        hybrid_score=0.5,
    ).model_dump(mode="json")


def test_incidental_general_table_does_not_suppress_table_only_candidate_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[SearchFilters] = []

    def fake_search(
        self: HybridRetriever,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
        queries: Sequence[str] | None = None,
        timings_ms: dict[str, int] | None = None,
    ) -> list[RetrievalCandidate]:
        del self, session, query, limit, queries, timings_ms
        calls.append(filters)
        return [
            RetrievalCandidate(
                chunk_id=22,
                text="Relevant quarterly results table with net income and revenue.",
                metadata={"element_type": "table", "ticker": "AAPL"},
                hybrid_score=0.9,
            )
        ]

    monkeypatch.setattr(HybridRetriever, "search", fake_search)
    state = cast(
        AnswerWorkflowState,
        {
            "user_query": "What were Apple's quarterly results?",
            "rewritten_queries": [
                "What were Apple's quarterly results?",
                "What were Apple's quarterly results? SEC filing financial results",
            ],
            "filters": SearchFilters(tickers=["AAPL"]).model_dump(mode="json"),
            "route": ["text", "tables", "financial_facts"],
            # A general mixed-element retrieval happened to return a table, but it
            # is not proof that the relevant table survived candidate generation.
            "text_candidates": [_table(11, "Incidental stock-compensation table.")],
            "trace": [],
        },
    )

    result = retrieve_tables_node(_context(), state)

    assert len(calls) == 1
    assert calls[0].tickers == ["AAPL"]
    assert calls[0].element_types == ["table"]
    assert [candidate["chunk_id"] for candidate in result["table_candidates"]] == [22]
    assert result["trace"][-1]["details"] == {"count": 1, "reused": False}


def test_table_only_primary_retrieval_reuses_existing_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_search(*args: object, **kwargs: object) -> list[RetrievalCandidate]:
        del args, kwargs
        raise AssertionError("table-only primary retrieval should be reused")

    monkeypatch.setattr(HybridRetriever, "search", fail_search)
    existing = _table(11, "Net sales by segment table.")
    state = cast(
        AnswerWorkflowState,
        {
            "user_query": "Find the table showing Apple segment revenue",
            "rewritten_queries": ["Find the table showing Apple segment revenue"],
            "filters": SearchFilters(
                tickers=["AAPL"],
                element_types=["table"],
            ).model_dump(mode="json"),
            "route": ["text", "tables", "financial_facts"],
            "text_candidates": [existing],
            "trace": [],
        },
    )

    result = retrieve_tables_node(_context(), state)

    assert result["table_candidates"] == [existing]
    assert result["trace"][-1]["details"] == {"count": 1, "reused": True}
