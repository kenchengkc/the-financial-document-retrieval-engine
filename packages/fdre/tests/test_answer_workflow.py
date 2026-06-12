from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, FinancialFact
from fdre.citations.verifier import AnswerClaim, CitationVerifier
from fdre.graph.nodes import GeneratedAnswer, MockAnswerGenerator, WorkflowContext
from fdre.graph.workflow import run_answer_workflow
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.retrieval.query import RetrievalCandidate


class UnsupportedAnswerGenerator:
    def generate(
        self,
        question: str,
        evidence: list[RetrievalCandidate],
    ) -> GeneratedAnswer:
        del question, evidence
        return GeneratedAnswer(
            answer_text="An unsupported answer.",
            claims=[
                AnswerClaim(
                    claim_text="An unsupported answer.",
                    citation_chunk_ids=[999],
                    citation_text="This text was not retrieved.",
                )
            ],
            confidence=0.9,
        )


def _seed(session: Session, *, include_table: bool = False, include_fact: bool = False) -> None:
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=date(2025, 10, 31),
        accepted_at=datetime(2025, 10, 31, 6, tzinfo=UTC),
        available_at=datetime(2025, 10, 31, 6, tzinfo=UTC),
        accession_number="0000320193-25-000079",
    )
    elements = [
        (
            "text",
            "Risk Factors",
            "Supply constraints may affect product availability and customer demand.",
        ),
        (
            "text",
            "Business",
            "Management increased infrastructure investment to support future services.",
        ),
    ]
    if include_table:
        elements.append(
            (
                "table",
                "Financial Statements",
                "Net sales by segment were 100 for Products and 50 for Services.",
            )
        )
    for order, (element_type, section, text) in enumerate(elements, start=1):
        element = DocumentElement(
            document=document,
            element_type=element_type,
            section=section,
            text=text,
            reading_order=order,
        )
        document.chunks.append(
            Chunk(
                element=element,
                chunk_text=text,
                chunk_type="table_markdown" if element_type == "table" else "text",
                section=section,
                page_start=order,
                page_end=order,
                token_count=len(text.split()),
                metadata_json={
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "company_name": "Apple Inc.",
                    "form_type": "10-K",
                    "filing_date": "2025-10-31",
                    "section": section,
                    "element_type": element_type,
                    "page_number": order,
                },
            )
        )
    if include_fact:
        company.financial_facts.append(
            FinancialFact(
                document=document,
                ticker="AAPL",
                fact_key="answer-workflow-revenue",
                taxonomy="us-gaap",
                concept="Revenues",
                canonical_metric="revenue",
                label="Revenue",
                value=Decimal("391035000000"),
                unit="USD",
                period_start=date(2024, 9, 29),
                period_end=date(2025, 9, 27),
                period_type="duration",
                fiscal_year=2025,
                fiscal_period="FY",
                form_type="10-K",
                accession_number=document.accession_number,
                available_at=document.available_at,
            )
        )
    session.add(company)
    session.commit()
    rebuild_embeddings(session, LocalHashEmbeddingProvider())


def _context(
    session: Session,
    *,
    generator: MockAnswerGenerator | UnsupportedAnswerGenerator | None = None,
    minimum_evidence: int = 1,
) -> WorkflowContext:
    return WorkflowContext(
        session=session,
        settings=Settings(
            EMBEDDING_PROVIDER="local_hash",
            EMBEDDING_MODEL="local-hash-v1",
            RERANKER_PROVIDER="fake",
            MIN_EVIDENCE_CHUNKS=minimum_evidence,
            MIN_RETRIEVAL_SCORE=0,
        ),
        generator=generator or MockAnswerGenerator(),
        verifier=CitationVerifier(),
    )


def test_answer_workflow_returns_verified_citations_and_trace() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        state = run_answer_workflow(
            _context(session),
            "What did Apple say about supply constraints?",
        )

    assert state["should_abstain"] is False
    assert state["answer"]
    assert state["citations"]
    assert state["citations"][0]["metadata"]["ticker"] == "AAPL"
    assert [step["node"] for step in state["trace"]] == [
        "preprocess_query",
        "route_tools",
        "retrieve_text",
        "retrieve_tables",
        "retrieve_financial_facts",
        "merge_candidates",
        "rerank",
        "evaluate_retrieval_gate",
        "generate_answer",
        "verify_citations",
        "finalize_or_abstain",
    ]


def test_answer_workflow_routes_tables_and_financial_facts() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session, include_table=True, include_fact=True)
        table_state = run_answer_workflow(
            _context(session),
            "Find the table showing Apple segment revenue",
        )
        fact_state = run_answer_workflow(
            _context(session),
            "Compare Apple revenue growth with management commentary",
        )

    assert "tables" in table_state["route"]
    assert table_state["evidence"][0]["metadata"]["element_type"] == "table"
    assert "financial_facts" in fact_state["route"]
    assert fact_state["financial_facts"][0]["concept"] == "Revenues"


def test_answer_workflow_abstains_on_weak_or_private_questions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        weak_state = run_answer_workflow(
            _context(session, minimum_evidence=5),
            "What did Apple disclose?",
        )
        private_state = run_answer_workflow(
            _context(session),
            "What private non-public information does Apple have?",
        )
        forecast_state = run_answer_workflow(
            _context(session),
            "Predict Apple's stock price and tell me whether to buy the stock.",
        )

    assert weak_state["should_abstain"] is True
    assert weak_state["answer"] is None
    assert private_state["should_abstain"] is True
    assert "non-public" in (private_state["abstention_reason"] or "")
    assert forecast_state["should_abstain"] is True
    assert "does not forecast" in (forecast_state["abstention_reason"] or "")


def test_answer_workflow_rejects_non_retrieved_citation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        state = run_answer_workflow(
            _context(session, generator=UnsupportedAnswerGenerator()),
            "What did Apple disclose?",
        )

    assert state["should_abstain"] is True
    assert state["answer"] is None
    assert "Citation chunk 999 was not retrieved" in state["errors"]
