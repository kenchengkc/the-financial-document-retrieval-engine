from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from scripts.ingest_sec_sample import ingest_sec_metadata
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.research.filing_diffs import compare_filing_to_prior, select_comparable_document
from fdre.retrieval.query import SearchFilters, chunk_matches_filters


def _document(
    company: Company,
    *,
    accession: str,
    form_type: str,
    period_end: date,
    accepted_at: datetime,
    passages: list[str],
) -> Document:
    document = Document(
        company=company,
        source_type="sec",
        form_type=form_type,
        filing_date=accepted_at.date(),
        period_end_date=period_end,
        accepted_at=accepted_at,
        available_at=accepted_at,
        accession_number=accession,
    )
    for order, passage in enumerate(passages, start=1):
        document.elements.append(
            DocumentElement(
                element_type="text",
                section="Risk Factors",
                text=passage,
                reading_order=order,
            )
        )
    return document


def test_as_of_filter_rejects_future_chunks_and_requires_timezone() -> None:
    future = datetime(2026, 8, 1, 12, tzinfo=UTC)
    chunk = Chunk(
        document_id=1,
        element_id=1,
        chunk_text="Future disclosure",
        chunk_type="text",
        metadata_json={
            "available_at": future.isoformat(),
            "accepted_at": future.isoformat(),
            "is_amendment": False,
        },
    )

    assert not chunk_matches_filters(
        chunk,
        SearchFilters(as_of=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    assert chunk_matches_filters(
        chunk,
        SearchFilters(as_of=datetime(2026, 9, 1, tzinfo=UTC)),
    )
    with pytest.raises(ValueError, match="UTC offset"):
        SearchFilters(as_of=datetime(2026, 7, 1))


def test_comparable_period_and_filing_difference_are_deterministic() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    previous = _document(
        company,
        accession="0000320193-24-000100",
        form_type="10-K",
        period_end=date(2024, 9, 28),
        accepted_at=datetime(2024, 11, 1, 12, tzinfo=UTC),
        passages=["Removed risk language.", "Common unchanged disclosure."],
    )
    current = _document(
        company,
        accession="0000320193-25-000100",
        form_type="10-K",
        period_end=date(2025, 9, 27),
        accepted_at=datetime(2025, 10, 31, 12, tzinfo=UTC),
        passages=["Common unchanged disclosure.", "Added AI regulation language."],
    )
    changed = _document(
        company,
        accession="0000320193-26-000100",
        form_type="10-K",
        period_end=date(2026, 9, 26),
        accepted_at=datetime(2026, 10, 30, 12, tzinfo=UTC),
        passages=["Common materially revised disclosure."],
    )

    with Session(engine) as session:
        session.add(company)
        session.commit()
        difference = compare_filing_to_prior(session, current.accession_number)
        changed_difference = compare_filing_to_prior(session, changed.accession_number)

    assert difference.comparison_basis == "prior_annual_period"
    assert difference.previous_accession == previous.accession_number
    assert difference.added_count == 1
    assert difference.removed_count == 1
    assert changed_difference.materially_changed_count == 1


def test_quarterly_comparison_prefers_same_quarter_prior_year() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="NVDA", cik="0001045810", name="NVIDIA Corporation")
    prior_year = _document(
        company,
        accession="q-prior-year",
        form_type="10-Q",
        period_end=date(2025, 4, 27),
        accepted_at=datetime(2025, 5, 28, tzinfo=UTC),
        passages=["Prior-year quarter."],
    )
    recent_quarter = _document(
        company,
        accession="q-recent",
        form_type="10-Q",
        period_end=date(2026, 1, 25),
        accepted_at=datetime(2026, 2, 25, tzinfo=UTC),
        passages=["Most recent quarter."],
    )
    current = _document(
        company,
        accession="q-current",
        form_type="10-Q",
        period_end=date(2026, 4, 26),
        accepted_at=datetime(2026, 5, 27, tzinfo=UTC),
        passages=["Current quarter."],
    )

    with Session(engine) as session:
        session.add(company)
        session.commit()
        comparable, basis = select_comparable_document(session, current)

    assert comparable is not None
    assert comparable.accession_number == prior_year.accession_number
    assert comparable.accession_number != recent_quarter.accession_number
    assert basis == "same_quarter_prior_year"


class _SubmissionsClient:
    def get_company_submissions(self, _cik: str) -> dict[str, object]:
        return {
            "name": "Apple Inc.",
            "exchanges": ["Nasdaq"],
            "filings": {
                "recent": {
                    "accessionNumber": [
                        "0000320193-25-000080",
                        "0000320193-25-000079",
                    ],
                    "filingDate": ["2025-11-03", "2025-10-31"],
                    "reportDate": ["2025-09-27", "2025-09-27"],
                    "acceptanceDateTime": [
                        "2025-11-03T14:30:00.000Z",
                        "2025-10-31T06:01:26.000Z",
                    ],
                    "form": ["10-K/A", "10-K"],
                    "primaryDocument": ["aapl-20250927x10ka.htm", "aapl-20250927.htm"],
                }
            },
        }


def test_ingestion_promotes_acceptance_time_and_amendment_lineage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        ingest_sec_metadata(
            session,
            client=_SubmissionsClient(),  # type: ignore[arg-type]
            tickers=["AAPL"],
            form_types=["10-K", "10-K/A"],
            limit=1,
        )
        documents = {
            document.form_type: document
            for document in session.query(Document).order_by(Document.form_type)
        }

    assert documents["10-K"].accepted_at is not None
    assert documents["10-K"].accepted_at.replace(tzinfo=UTC) == datetime(
        2025,
        10,
        31,
        6,
        1,
        26,
        tzinfo=UTC,
    )
    assert documents["10-K/A"].is_amendment
    assert (
        documents["10-K/A"].amends_accession_number
        == documents["10-K"].accession_number
    )
