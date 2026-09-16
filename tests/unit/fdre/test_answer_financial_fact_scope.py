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
from fdre.retrieval.query import SearchFilters


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
    context = WorkflowContext(
        session=cast(Session, object()),
        settings=Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            RERANKER_PROVIDER="fake",
        ),
        generator=ExtractiveAnswerGenerator(),
        verifier=CitationVerifier(),
    )
    state: AnswerWorkflowState = {
        "user_query": "Compare revenue growth across companies",
        "route": ["text", "financial_facts"],
        "filters": SearchFilters().model_dump(mode="json"),
    }

    result = answer_nodes.retrieve_financial_facts_node(context, state)

    assert called is False
    assert result["financial_facts"] == []
    trace = result["trace"][-1]
    assert trace["details"] == {
        "count": 0,
        "skipped": True,
        "reason": "issuer_scope_required",
    }
