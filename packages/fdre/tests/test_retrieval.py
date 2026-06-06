from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.query import SearchFilters
from fdre.retrieval.rerank import FakeReranker
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
