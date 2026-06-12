from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, FinancialFact
from fdre.ingestion.xbrl import normalize_company_facts
from fdre.research.financial_facts import FinancialFactQuery, query_financial_facts


def _document(
    company: Company,
    *,
    accession: str,
    form_type: str,
    available_at: datetime,
) -> Document:
    document = Document(
        company=company,
        source_type="sec",
        form_type=form_type,
        filing_date=available_at.date(),
        period_end_date=date(2024, 12, 31),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=form_type.endswith("/A"),
        accession_number=accession,
        primary_document_url=f"https://www.sec.gov/{accession}.htm",
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        section="MD&A",
        text="Revenue increased because customer demand remained strong.",
        reading_order=1,
    )
    document.chunks.append(
        Chunk(
            element=element,
            chunk_text=element.text or "",
            chunk_type="text",
            section=element.section,
            metadata_json={
                "ticker": company.ticker,
                "accession_number": accession,
                "section": element.section,
            },
        )
    )
    return document


def _payload() -> dict[str, object]:
    original = {
        "start": "2024-01-01",
        "end": "2024-12-31",
        "val": 100,
        "accn": "original",
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "filed": "2025-02-01",
        "frame": "CY2024",
    }
    amended = {
        **original,
        "val": 110,
        "accn": "amendment",
        "form": "10-K/A",
        "filed": "2025-03-01",
    }
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "description": "Revenue recognized from customers.",
                    "units": {"USD": [original, amended]},
                }
            },
            "dei": {
                "EntityPublicFloat": {
                    "label": "Public float",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-06-30",
                                "val": 500,
                                "accn": "original",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    },
                }
            },
        }
    }


def test_xbrl_normalization_preserves_raw_facts_and_restatements() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="TEST", cik="0000000001", name="Test Company")
    original = _document(
        company,
        accession="original",
        form_type="10-K",
        available_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    amendment = _document(
        company,
        accession="amendment",
        form_type="10-K/A",
        available_at=datetime(2025, 3, 1, tzinfo=UTC),
    )
    amendment.amends_accession_number = original.accession_number

    with Session(engine) as session:
        session.add(company)
        session.commit()
        facts, seen, skipped = normalize_company_facts(session, company, _payload())
        session.add_all(facts)
        session.commit()

        stored = list(session.scalars(select(FinancialFact).order_by(FinancialFact.id)))
        latest = query_financial_facts(
            session,
            FinancialFactQuery(tickers=["TEST"], metrics=["revenue"]),
        )
        as_reported = query_financial_facts(
            session,
            FinancialFactQuery(
                tickers=["TEST"],
                metrics=["revenue"],
                as_of=datetime(2025, 2, 15, tzinfo=UTC),
            ),
        )

    assert seen == 3
    assert skipped == 0
    assert len(stored) == 3
    assert any(fact.taxonomy == "dei" and fact.canonical_metric is None for fact in stored)
    restatement = next(fact for fact in stored if fact.accession_number == "amendment")
    assert restatement.is_restatement
    assert restatement.metadata_json is not None
    assert restatement.metadata_json["raw_fact"]["val"] == 110
    assert latest.facts[0].value == Decimal("110")
    assert latest.facts[0].narrative_evidence is not None
    assert latest.facts[0].narrative_evidence.accession_number == "amendment"
    assert as_reported.facts[0].value == Decimal("100")
