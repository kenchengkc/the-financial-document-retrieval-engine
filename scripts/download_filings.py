from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.ingestion.ticker_map import DEFAULT_SAMPLE_TICKERS
from scripts.ingest_sec_sample import DEFAULT_FORMS


@dataclass(frozen=True, slots=True)
class ProcessingSummary:
    selected: int = 0
    downloaded: int = 0
    skipped_downloads: int = 0


def select_documents(
    session: Session,
    *,
    tickers: list[str],
    form_types: list[str],
    limit: int,
) -> list[Document]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    documents = session.scalars(
        select(Document)
        .join(Document.company)
        .options(joinedload(Document.company))
        .where(
            Company.ticker.in_([ticker.upper() for ticker in tickers]),
            Document.form_type.in_([form.upper() for form in form_types]),
        )
        .order_by(Company.ticker, Document.form_type, Document.filing_date.desc())
    ).all()

    counts: dict[tuple[str, str], int] = {}
    selected: list[Document] = []
    for document in documents:
        key = (document.company.ticker, document.form_type)
        count = counts.get(key, 0)
        if count >= limit:
            continue
        selected.append(document)
        counts[key] = count + 1
    return selected


def process_documents(
    session: Session,
    *,
    downloader: SECFilingDownloader | None,
    tickers: list[str],
    form_types: list[str],
    limit: int,
    download: bool,
) -> ProcessingSummary:
    documents = select_documents(
        session,
        tickers=tickers,
        form_types=form_types,
        limit=limit,
    )
    downloaded = 0
    skipped_downloads = 0

    for document in documents:
        if download:
            if downloader is None:
                raise ValueError("A downloader is required when download=True")
            primary_document = _primary_document(document)
            result = downloader.download(
                cik=document.company.cik,
                accession_number=document.accession_number,
                primary_document=primary_document,
                expected_sha256=document.sha256_hash,
            )
            document.local_path = str(result.local_path)
            document.sha256_hash = result.sha256_hash
            if result.downloaded:
                downloaded += 1
            else:
                skipped_downloads += 1

    session.commit()
    return ProcessingSummary(
        selected=len(documents),
        downloaded=downloaded,
        skipped_downloads=skipped_downloads,
    )


def _primary_document(document: Document) -> str:
    metadata = document.metadata_json or {}
    primary_document = metadata.get("primary_document")
    if isinstance(primary_document, str) and primary_document:
        return primary_document
    if document.primary_document_url:
        return Path(document.primary_document_url).name
    raise ValueError(f"Document {document.accession_number} has no primary document filename")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download SEC filings already in FDRE")
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_SAMPLE_TICKERS))
    parser.add_argument("--forms", nargs="+", default=list(DEFAULT_FORMS))
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--download", action="store_true", help="Download selected filing HTML")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Session(create_db_engine()) as session:
        if args.download:
            with SECClient.from_settings() as client:
                summary = process_documents(
                    session,
                    downloader=SECFilingDownloader(client),
                    tickers=args.tickers,
                    form_types=args.forms,
                    limit=args.limit,
                    download=True,
                )
        else:
            summary = process_documents(
                session,
                downloader=None,
                tickers=args.tickers,
                form_types=args.forms,
                limit=args.limit,
                download=False,
            )
    print(summary)


if __name__ == "__main__":
    main()
