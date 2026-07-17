from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, FinancialFact
from fdre.citations.verifier import AnswerClaim, CitationVerifier
from fdre.graph.nodes import (
    UNSUPPORTED_FORECAST_PATTERN,
    GeneratedAnswer,
    MockAnswerGenerator,
    WorkflowContext,
)
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


def test_latest_query_only_retrieves_the_newest_indexed_filing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed(session)
        company = session.scalar(select(Company).where(Company.ticker == "AAPL"))
        assert company is not None
        older_document = Document(
            company=company,
            source_type="sec",
            form_type="10-K",
            filing_date=date(2024, 11, 1),
            accepted_at=datetime(2024, 11, 1, 6, tzinfo=UTC),
            available_at=datetime(2024, 11, 1, 6, tzinfo=UTC),
            accession_number="0000320193-24-000123",
        )
        older_element = DocumentElement(
            document=older_document,
            element_type="text",
            section="Risk Factors",
            text=(
                "Supply chain changes involve significant risks and uncertainties "
                "for Apple and its outsourcing partners."
            ),
            reading_order=1,
        )
        older_document.chunks.append(
            Chunk(
                element=older_element,
                chunk_text=older_element.text or "",
                chunk_type="text",
                section=older_element.section,
                token_count=12,
                metadata_json={
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "company_name": "Apple Inc.",
                    "form_type": "10-K",
                    "filing_date": "2024-11-01",
                    "section": "Risk Factors",
                    "element_type": "text",
                    "page_number": 1,
                },
            )
        )
        session.add(older_document)
        session.commit()
        rebuild_embeddings(session, LocalHashEmbeddingProvider())

        state = run_answer_workflow(
            _context(session),
            "What supply-chain risks did Apple disclose in its latest 10-K?",
        )

    evidence_dates = {
        candidate["metadata"].get("filing_date") for candidate in state["evidence"]
    }
    assert evidence_dates == {"2025-10-31"}
    preprocess_trace = next(
        step for step in state["trace"] if step["node"] == "preprocess_query"
    )
    assert preprocess_trace["details"]["filters"]["filing_date_from"] == "2025-10-31"
    assert preprocess_trace["details"]["filters"]["filing_date_to"] == "2025-10-31"


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
    table_trace = next(
        step for step in table_state["trace"] if step["node"] == "retrieve_tables"
    )
    assert table_trace["details"]["reused"] is True
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


def test_forecast_guard_flags_future_price_questions_without_false_positives() -> None:
    forecast_questions = [
        "What will NVIDIA's stock price be next quarter?",
        "Predict Apple's stock price and tell me whether to buy the stock.",
        "Where is the share price headed next year?",
        "Should I buy the stock?",
        "Give me a price target for the stock.",
    ]
    for question in forecast_questions:
        assert UNSUPPORTED_FORECAST_PATTERN.search(question), question

    grounded_questions = [
        "How did Apple's stock price perform over the past five years?",
        "What did the company disclose about stock-based compensation?",
        "What did META report for earnings last quarter?",
        "What did Apple say about supply chain risk in its latest 10-K?",
    ]
    for question in grounded_questions:
        assert not UNSUPPORTED_FORECAST_PATTERN.search(question), question


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


def test_extractive_answer_preserves_decimal_financial_values() -> None:
    answer = MockAnswerGenerator().generate(
        "What did META report for earnings last quarter?",
        [
            RetrievalCandidate(
                chunk_id=2,
                text=(
                    "Our Quarterly Reports on Form 10-Q are filed with the U.S. "
                    "Securities and Exchange Commission."
                ),
                metadata={"element_type": "text", "ticker": "META"},
                rerank_score=0.9,
            ),
            RetrievalCandidate(
                chunk_id=1,
                text=(
                    "• Net income was $26.77 billion, with diluted earnings per share "
                    "of $10.44 for the quarter. Revenue also increased."
                ),
                metadata={"element_type": "text", "ticker": "META"},
                rerank_score=0.8,
            )
        ],
    )

    assert answer.answer_text == (
        "Net income was $26.77 billion, with diluted earnings per share "
        "of $10.44 for the quarter."
    )
