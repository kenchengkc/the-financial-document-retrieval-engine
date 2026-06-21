from __future__ import annotations

import pytest
import respx
from httpx import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.rerank import FakeReranker, VoyageReranker, reranker_from_settings
from fdre.retrieval.sparse import SparseRetriever


def _seed_retrieval_data(session: Session) -> None:
    company = Company(ticker="NVDA", cik="0001045810", name="NVIDIA Corporation")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0001045810-25-000023",
    )
    for order, (section, text) in enumerate(
        [
            ("Business", "Data center revenue increased with AI demand."),
            ("Risk Factors", "Export controls may restrict product sales."),
            ("Business", "Gaming revenue also increased."),
        ],
        start=1,
    ):
        element = DocumentElement(
            document=document,
            element_type="text",
            section=section,
            text=text,
            reading_order=order,
        )
        document.chunks.append(
            Chunk(
                element=element,
                chunk_text=text,
                chunk_type="text",
                section=section,
                token_count=len(text.split()),
                metadata_json={
                    "ticker": "NVDA",
                    "cik": "0001045810",
                    "form_type": "10-K",
                    "section": section,
                    "element_type": "text",
                },
            )
        )
    session.add(company)
    session.commit()


def test_dense_sparse_hybrid_and_reranking() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = LocalHashEmbeddingProvider(dimensions=32)
    with Session(engine) as session:
        _seed_retrieval_data(session)
        rebuild_embeddings(session, provider)
        filters = SearchFilters(tickers=["NVDA"], sections=["Business"])
        dense = DenseRetriever(provider)
        sparse = SparseRetriever()
        dense_results = dense.search(
            session,
            "AI data center revenue",
            filters=filters,
            limit=5,
        )
        sparse_results = sparse.search(
            session,
            "AI data center revenue",
            filters=filters,
            limit=5,
        )
        hybrid_results = HybridRetriever(dense, sparse).search(
            session,
            "AI data center revenue",
            filters=filters,
            limit=5,
        )
        reranked = FakeReranker().rerank(
            "gaming revenue",
            hybrid_results,
            top_n=2,
        )

        assert dense_results
        assert sparse_results
        assert len({result.chunk_id for result in hybrid_results}) == len(hybrid_results)
        assert all(result.metadata["section"] == "Business" for result in hybrid_results)
        assert any(result.dense_score is not None for result in hybrid_results)
        assert any(result.sparse_score is not None for result in hybrid_results)
        assert reranked[0].rerank_score is not None
        assert "Gaming" in reranked[0].text


def test_reciprocal_rank_fusion_rewards_agreement_and_top_ranks() -> None:
    # id 1 is rank-1 in both lists; id 2 and 3 sit lower / appear in one list each.
    dense = (1.0, [1, 3, 4])
    sparse = (1.0, [1, 2, 5])
    scores = reciprocal_rank_fusion([dense, sparse], k=60)
    ranked = sorted(scores, key=lambda i: -scores[i])
    assert ranked[0] == 1  # agreed top of both lists wins
    assert scores[1] > scores[3] and scores[1] > scores[2]
    # weighting one ranker higher lifts its exclusive ids
    weighted = reciprocal_rank_fusion([(0.1, [1, 3, 4]), (1.0, [2, 1, 5])], k=60)
    assert weighted[2] > weighted[3]


def _candidate(chunk_id: int, text: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id, text=text, metadata={"ticker": "AAPL"}, hybrid_score=0.5
    )


@respx.mock
def test_voyage_reranker_orders_by_relevance() -> None:
    respx.post("https://api.voyageai.com/v1/rerank").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.40},
                ]
            },
        )
    )
    candidates = [
        _candidate(10, "supply chain risk"),
        _candidate(11, "incorporated by reference"),
        _candidate(12, "export controls disproportionately impact us"),
    ]
    reranked = VoyageReranker(api_key="test-key", model="rerank-2.5").rerank(
        "export controls", candidates, top_n=2
    )

    # Voyage returns top_k ordered by relevance; index maps back to the input candidate.
    assert [candidate.chunk_id for candidate in reranked] == [12, 10]
    assert reranked[0].rerank_score == 0.95
    assert [candidate.rank for candidate in reranked] == [1, 2]


def test_reranker_from_settings_voyage() -> None:
    with_key = Settings.model_construct(
        reranker_provider="voyage", reranker_model="rerank-2.5", voyage_api_key="k"
    )
    assert isinstance(reranker_from_settings(with_key), VoyageReranker)

    without_key = Settings.model_construct(
        reranker_provider="voyage", reranker_model="rerank-2.5", voyage_api_key=None
    )
    with pytest.raises(ValueError):
        reranker_from_settings(without_key)
