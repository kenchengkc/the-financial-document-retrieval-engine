from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, Document, DocumentElement
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.ingestion.ticker_map import DEFAULT_SAMPLE_TICKERS
from fdre.parsing.html_filing_parser import HtmlFilingParser
from scripts.ingest_sec_sample import DEFAULT_FORMS


@dataclass(frozen=True, slots=True)
class ProcessingSummary:
    selected: int = 0
    downloaded: int = 0
    skipped_downloads: int = 0
    parsed_documents: int = 0
    parsed_elements: int = 0


def select_documents(
    session: Session,
    *,
    tickers: list[str],
    form_types: list[str],
    limit: int | Mapping[str, int],
) -> list[Document]:
    form_limits = (
        {form.upper(): limit for form in form_types}
        if isinstance(limit, int)
        else {form.upper(): value for form, value in limit.items()}
    )
    if any(value < 1 for value in form_limits.values()):
        raise ValueError("form limits must be at least 1")

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
        if count >= form_limits[document.form_type.upper()]:
            continue
        selected.append(document)
        counts[key] = count + 1
    return selected


def process_documents(
    session: Session,
    *,
    downloader: SECFilingDownloader | None,
    parser: HtmlFilingParser,
    tickers: list[str],
    form_types: list[str],
    limit: int | Mapping[str, int],
    download: bool,
    parse: bool,
    force_parse: bool = False,
) -> ProcessingSummary:
    documents = select_documents(
        session,
        tickers=tickers,
        form_types=form_types,
        limit=limit,
    )
    downloaded = 0
    skipped_downloads = 0
    parsed_documents = 0
    parsed_elements = 0

    for document in documents:
        content_changed = True
        if download:
            if downloader is None:
                raise ValueError("A downloader is required when download=True")
            previous_sha256 = document.sha256_hash
            primary_document = _primary_document(document)
            result = downloader.download(
                cik=document.company.cik,
                accession_number=document.accession_number,
                primary_document=primary_document,
                expected_sha256=document.sha256_hash,
            )
            document.local_path = str(result.local_path)
            document.sha256_hash = result.sha256_hash
            content_changed = previous_sha256 != result.sha256_hash
            if result.downloaded:
                downloaded += 1
            else:
                skipped_downloads += 1

        if parse:
            has_elements = session.scalar(
                select(DocumentElement.id)
                .where(DocumentElement.document_id == document.id)
                .limit(1)
            ) is not None
            if has_elements and not content_changed and not force_parse:
                continue
            if not document.local_path:
                raise ValueError(
                    f"Document {document.accession_number} has no local file; use --download first"
                )
            elements = parser.parse_file(document.local_path)
            session.execute(
                delete(DocumentElement).where(DocumentElement.document_id == document.id)
            )
            session.add_all(
                [
                    DocumentElement(
                        document_id=document.id,
                        element_type=element.element_type,
                        page_number=element.page_number,
                        section=element.section,
                        text=element.text,
                        markdown=element.markdown,
                        json_payload=element.metadata,
                        bbox=element.bbox,
                        reading_order=element.reading_order,
                    )
                    for element in elements
                ]
            )
            parsed_documents += 1
            parsed_elements += len(elements)

    session.commit()
    return ProcessingSummary(
        selected=len(documents),
        downloaded=downloaded,
        skipped_downloads=skipped_downloads,
        parsed_documents=parsed_documents,
        parsed_elements=parsed_elements,
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
    parser = argparse.ArgumentParser(description="Download and parse SEC filings already in FDRE")
    parser.add_argument("--tickers", nargs="+", default=list(DEFAULT_SAMPLE_TICKERS))
    parser.add_argument("--forms", nargs="+", default=list(DEFAULT_FORMS))
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--annual-limit", type=int)
    parser.add_argument("--quarterly-limit", type=int)
    parser.add_argument("--download", action="store_true", help="Download selected filing HTML")
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Replace document elements from downloaded HTML",
    )
    parser.add_argument(
        "--force-parse",
        action="store_true",
        help="Reparse selected filings even when their downloaded content is unchanged",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    limit: int | dict[str, int] = args.limit
    if args.annual_limit is not None or args.quarterly_limit is not None:
        limit = {
            form.upper(): (
                args.annual_limit
                if form.upper().startswith("10-K") and args.annual_limit is not None
                else args.quarterly_limit
                if form.upper().startswith("10-Q") and args.quarterly_limit is not None
                else args.limit
            )
            for form in args.forms
        }
    with Session(create_db_engine()) as session:
        if args.download:
            with SECClient.from_settings() as client:
                summary = process_documents(
                    session,
                    downloader=SECFilingDownloader(client),
                    parser=HtmlFilingParser(),
                    tickers=args.tickers,
                    form_types=args.forms,
                    limit=limit,
                    download=True,
                    parse=args.parse,
                    force_parse=args.force_parse,
                )
        else:
            summary = process_documents(
                session,
                downloader=None,
                parser=HtmlFilingParser(),
                tickers=args.tickers,
                form_types=args.forms,
                limit=limit,
                download=False,
                parse=args.parse,
                force_parse=args.force_parse,
            )
    print(summary)


if __name__ == "__main__":
    main()
