from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import (
    AnswerRun,
    Chunk,
    Citation,
    Company,
    Document,
    DocumentElement,
    Embedding,
    EvalQuestion,
    EvalResult,
    FinancialFact,
    ResearchExperiment,
    RetrievalResult,
    RetrievalRun,
)

EXPECTED_TABLES = {
    "answer_runs",
    "chunks",
    "citations",
    "companies",
    "document_elements",
    "documents",
    "embeddings",
    "eval_questions",
    "eval_results",
    "financial_facts",
    "retrieval_results",
    "retrieval_runs",
    "research_experiments",
}


def create_sqlite_engine() -> Engine:
    return create_engine("sqlite+pysqlite:///:memory:")


def test_metadata_creates_expected_tables_and_indexes() -> None:
    engine = create_sqlite_engine()
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == EXPECTED_TABLES

    expected_indexes = {
        "companies": {"cik", "ticker"},
        "documents": {"company_id", "filing_date", "form_type"},
        "document_elements": {"document_id", "element_type", "section"},
        "chunks": {"chunk_type", "document_id", "section"},
    }
    for table_name, indexed_columns in expected_indexes.items():
        actual_columns = {
            column
            for index in inspector.get_indexes(table_name)
            for column in index["column_names"]
        }
        assert indexed_columns <= actual_columns


def test_models_persist_related_financial_document_data() -> None:
    engine = create_sqlite_engine()
    Base.metadata.create_all(engine)

    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=date(2025, 10, 31),
        accession_number="0000320193-25-000079",
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        section="Risk Factors",
        text="Supply constraints may affect operations.",
        reading_order=1,
    )
    chunk = Chunk(
        document=document,
        element=element,
        chunk_text="Supply constraints may affect operations.",
        chunk_type="text",
        section="Risk Factors",
        token_count=6,
    )
    chunk.embeddings.append(
        Embedding(
            provider="fake",
            model="fake-v1",
            dimensions=3,
            vector=[0.1, 0.2, 0.3],
        )
    )
    company.financial_facts.append(
        FinancialFact(
            ticker="AAPL",
            concept="Revenues",
            value=Decimal("100.00"),
            unit="USD",
            fiscal_year=2025,
            form_type="10-K",
        )
    )
    retrieval_run = RetrievalRun(
        query="Apple supply chain risk",
        retriever_variant="hybrid",
        results=[RetrievalResult(chunk=chunk, rank=1, hybrid_score=0.91)],
    )
    answer_run = AnswerRun(
        question="What did Apple say about supply constraints?",
        answer_text="Apple identified supply constraints as an operating risk.",
        confidence=0.9,
        citations=[
            Citation(
                chunk=chunk,
                claim_text="Apple identified supply constraints as an operating risk.",
                citation_text="Supply constraints may affect operations.",
                section="Risk Factors",
                confidence=0.95,
            )
        ],
    )
    research_experiment = ResearchExperiment(
        experiment_key="event-study-test",
        experiment_type="event_study",
        dataset_version="dataset-v1",
        feature_version="feature-v1",
        code_sha="abc123",
        config_json={"windows": ["0:1"]},
        results_json={"sample_size": 1},
    )

    with Session(engine) as session:
        session.add_all(
            [
                company,
                retrieval_run,
                answer_run,
                research_experiment,
                EvalQuestion(
                    question_key="development-aapl-risk",
                    question="Find Apple's supply risk.",
                    split="development",
                    category="narrative",
                    relevant_evidence_json=[
                        {
                            "accession_number": "0000320193-25-000079",
                            "section": "Risk Factors",
                            "normalized_quote": "supply constraints may affect operations.",
                            "content_fingerprint": "0" * 64,
                        }
                    ],
                    answer_type="text",
                    should_abstain=False,
                    reviewed_by="test-reviewer",
                ),
                EvalResult(eval_run_id=1, metric_name="recall@5", metric_value=1.0),
            ]
        )
        session.commit()

        stored_company = session.scalar(select(Company).where(Company.ticker == "AAPL"))
        stored_retrieval_run = session.scalar(select(RetrievalRun))
        stored_answer_run = session.scalar(select(AnswerRun))

        assert stored_company is not None
        assert stored_retrieval_run is not None
        assert stored_answer_run is not None
        assert stored_company.documents[0].chunks[0].embeddings[0].dimensions == 3
        assert stored_company.financial_facts[0].concept == "Revenues"
        assert stored_retrieval_run.results[0].rank == 1
        assert stored_answer_run.citations[0].section == "Risk Factors"
