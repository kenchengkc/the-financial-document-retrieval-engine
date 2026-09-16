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
from fdre.retrieval.query import RetrievalCandidate


def test_narrative_growth_does_not_require_structured_financial_facts() -> None:
    candidate = RetrievalCandidate(
        chunk_id=1,
        text="Management described a growth strategy built on selective acquisitions.",
        metadata={"ticker": "AAPL", "element_type": "text"},
        rerank_score=0.9,
    )
    state: AnswerWorkflowState = {
        "user_query": "What growth strategy did Apple describe around acquisitions?",
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
        result = evaluate_retrieval_gate_node(context, state)

    assert result["should_abstain"] is False
    assert result["abstention_reason"] is None
