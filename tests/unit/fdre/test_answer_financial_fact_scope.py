from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from sqlalchemy.orm import Session

import fdre.answering.nodes as answer_nodes
from apps.api.app.config import Settings
from fdre.answering.nodes import ExtractiveAnswerGenerator, WorkflowContext
from fdre.answering.state import AnswerWorkflowState
from fdre.citations.verifier import CitationVerifier
from fdre.research.financial_facts import FinancialFactQuery, FinancialFactsResponse
from fdre.retrieval.query import SearchFilters


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


def test_answer_financial_facts_skip_unscoped_issuer_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_query(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("unscoped answer query must not read cross-issuer facts")

    monkeypatch.setattr(
        answer_nodes,
        "query_financial_facts",
        cast(Callable[..., object], unexpected_query),
    )
    state: AnswerWorkflowState = {
        "user_query": "Compare revenue growth across companies",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters().model_dump(mode="json"),
    }

    result = answer_nodes.retrieve_financial_facts_node(_context(), state)

    assert called is False
    assert result["financial_facts"] == []
    trace = result["trace"][-1]
    assert trace["details"] == {
        "count": 0,
        "skipped": True,
        "reason": "issuer_scope_required",
    }


def test_answer_financial_facts_scope_explicit_revenue_query_to_revenue_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[FinancialFactQuery] = []

    def capture_query(
        _session: Session,
        query: FinancialFactQuery,
    ) -> FinancialFactsResponse:
        observed.append(query)
        return FinancialFactsResponse(query=query, facts=[])

    monkeypatch.setattr(answer_nodes, "query_financial_facts", capture_query)
    state: AnswerWorkflowState = {
        "user_query": "What was Apple's revenue growth?",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters(tickers=["AAPL"]).model_dump(mode="json"),
    }

    answer_nodes.retrieve_financial_facts_node(_context(), state)

    assert len(observed) == 1
    assert observed[0].tickers == ["AAPL"]
    assert observed[0].metrics == ["revenue"]


def test_answer_financial_facts_fail_closed_for_unsupported_required_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_query(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError(
            "unsupported required metrics must not be satisfied by unrelated facts"
        )

    monkeypatch.setattr(
        answer_nodes,
        "query_financial_facts",
        cast(Callable[..., object], unexpected_query),
    )
    state: AnswerWorkflowState = {
        "user_query": "What was Apple's asset growth?",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters(tickers=["AAPL"]).model_dump(mode="json"),
    }

    result = answer_nodes.retrieve_financial_facts_node(_context(), state)

    assert called is False
    assert result["financial_facts"] == []
    trace = result["trace"][-1]
    assert trace["details"] == {
        "count": 0,
        "skipped": True,
        "reason": "unsupported_required_metric",
    }
