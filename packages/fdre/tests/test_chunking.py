from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.chunking import ElementChunker, TableChunker, rebuild_document_chunks


def test_text_chunks_respect_token_budget_and_element_section() -> None:
    element = DocumentElement(
        document_id=1,
        element_type="text",
        section="Risk Factors",
        text="one two three four five six seven",
        reading_order=1,
    )
    chunks = ElementChunker(max_tokens=3).chunk(
        element,
        metadata={"ticker": "AAPL", "element_id": 1},
    )

    assert [chunk.token_count for chunk in chunks] == [3, 3, 1]
    assert {chunk.section for chunk in chunks} == {"Risk Factors"}
    assert all(chunk.metadata["ticker"] == "AAPL" for chunk in chunks)


def test_table_chunking_preserves_markdown_and_metadata() -> None:
    element = DocumentElement(
        document_id=1,
        element_type="table",
        section="Financial Statements",
        markdown="| Year | Revenue |\n| --- | --- |\n| 2025 | 125 |",
        json_payload={"headers": ["Year", "Revenue"], "row_count": 1, "column_count": 2},
        reading_order=2,
    )
    chunks = TableChunker().chunk(
        element,
        metadata={"ticker": "AAPL", "element_id": 2},
    )

    assert [chunk.chunk_type for chunk in chunks] == ["table_markdown", "table_summary"]
    assert chunks[0].chunk_text.startswith("| Year | Revenue |")
    assert "Columns: Year, Revenue" in chunks[1].chunk_text
    assert chunks[0].metadata["row_count"] == 1


def test_rebuild_document_chunks_is_idempotent_and_propagates_metadata() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=date(2025, 10, 31),
        accession_number="0000320193-25-000079",
    )
    document.elements.extend(
        [
            DocumentElement(
                element_type="text",
                section="Business",
                text="Apple designs products and services.",
                reading_order=1,
            ),
            DocumentElement(
                element_type="table",
                section="Financial Statements",
                text="Year | Revenue",
                markdown="| Year | Revenue |\n| --- | --- |\n| 2025 | 125 |",
                json_payload={
                    "headers": ["Year", "Revenue"],
                    "row_count": 1,
                    "column_count": 2,
                },
                reading_order=2,
            ),
        ]
    )

    with Session(engine) as session:
        session.add(company)
        session.commit()
        first = rebuild_document_chunks(session, document.id, max_tokens=3)
        second = rebuild_document_chunks(session, document.id, max_tokens=3)
        stored = list(session.scalars(select(Chunk).order_by(Chunk.id)))

        assert len(first) == len(second) == len(stored) == 4
        assert {chunk.section for chunk in stored} == {
            "Business",
            "Financial Statements",
        }
        for chunk in stored:
            metadata = chunk.metadata_json or {}
            assert metadata["ticker"] == "AAPL"
            assert metadata["cik"] == "0000320193"
            assert metadata["form_type"] == "10-K"
            assert metadata["document_id"] == document.id
            assert metadata["element_id"] == chunk.element_id
