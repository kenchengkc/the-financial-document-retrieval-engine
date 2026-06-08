from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from fdre.ingestion.sec_client import (
    SECClient,
    build_primary_document_url,
    company_submissions_url,
    extract_recent_filings,
)
from fdre.ingestion.ticker_map import DEFAULT_SAMPLE_TICKERS, CompanySeed, get_company_seed

DEFAULT_FORMS = ("10-K", "10-Q")


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    companies_created: int = 0
    companies_updated: int = 0
    documents_created: int = 0
    documents_updated: int = 0


def ingest_sec_metadata(
    session: Session,
    *,
    client: SECClient,
    tickers: list[str],
    form_types: list[str],
    limit: int,
) -> IngestionSummary:
    counters = {
        "companies_created": 0,
        "companies_updated": 0,
        "documents_created": 0,
        "documents_updated": 0,
    }

    processed_ciks: set[str] = set()
    for ticker in tickers:
        seed = get_company_seed(ticker)
        if seed.cik in processed_ciks:
            continue
        processed_ciks.add(seed.cik)

        submissions = client.get_company_submissions(seed.cik)
        company, created = _resolve_company(session, seed, submissions)
        counters["companies_created" if created else "companies_updated"] += 1

        filings = extract_recent_filings(submissions, form_types, limit)
        for filing in filings:
            accession = str(filing["accession_number"])
            document = session.scalar(
                select(Document).where(
                    Document.company_id == company.id,
                    Document.accession_number == accession,
                )
            )
            created = document is None
            if document is None:
                document = Document(
                    company=company,
                    source_type="sec",
                    form_type=str(filing["form_type"]),
                    accession_number=accession,
                )
                session.add(document)

            primary_document = str(filing["primary_document"])
            document.source_type = "sec"
            document.form_type = str(filing["form_type"])
            document.filing_date = _parse_date(filing.get("filing_date"))
            document.period_end_date = _parse_date(filing.get("report_date"))
            document.primary_document_url = build_primary_document_url(
                seed.cik,
                accession,
                primary_document,
            )
            document.source_url = company_submissions_url(seed.cik)
            document.metadata_json = {
                key: value
                for key, value in filing.items()
                if key
                not in {
                    "accession_number",
                    "filing_date",
                    "form_type",
                    "report_date",
                }
                and value is not None
                and value != ""
            }
            counters["documents_created" if created else "documents_updated"] += 1

    session.commit()
    return IngestionSummary(**counters)


def _resolve_company(
    session: Session,
    seed: CompanySeed,
    submissions: dict[str, Any],
) -> tuple[Company, bool]:
    """Match by CIK first so dual-class tickers (GOOG/GOOGL) share one company row."""

    name = _string_value(submissions.get("name")) or seed.name
    exchange = _first_string(submissions.get("exchanges")) or seed.exchange
    company = session.scalar(select(Company).where(Company.cik == seed.cik))
    if company is None:
        company = session.scalar(select(Company).where(Company.ticker == seed.ticker))
    if company is None:
        company = Company(
            ticker=seed.ticker,
            cik=seed.cik,
            name=name,
            exchange=exchange,
        )
        session.add(company)
        session.flush()
        return company, True

    company.cik = seed.cik
    company.name = name
    company.exchange = exchange
    return company, False


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    return date.fromisoformat(value)


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_string(value: Any) -> str | None:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest sample SEC filing metadata into FDRE")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(DEFAULT_SAMPLE_TICKERS),
        help="Sample tickers to ingest",
    )
    parser.add_argument(
        "--forms",
        nargs="+",
        default=list(DEFAULT_FORMS),
        help="SEC filing forms to ingest",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Maximum filings per form and company",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SECClient.from_settings() as client, Session(create_db_engine()) as session:
        summary = ingest_sec_metadata(
            session,
            client=client,
            tickers=args.tickers,
            form_types=args.forms,
            limit=args.limit,
        )
    print(summary)


if __name__ == "__main__":
    main()
