"""Bounded, zero-embedding research archive for historical-universe issuers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.ingestion.sec_client import (
    SECClient,
    build_primary_document_url,
    company_submissions_url,
)
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.parsing.html_filing_parser import HtmlFilingParser
from fdre.research.panel import (
    ResearchPanelQuery,
    build_research_panel,
    write_research_panel,
)

ARCHIVE_PROFILE = "fdre-research-archive-v1"
DEFAULT_ARCHIVE_SECTIONS = ("Risk Factors",)


@dataclass(frozen=True, slots=True)
class ArchiveIssuer:
    company_id: int
    cik: str
    name: str


@dataclass(frozen=True, slots=True)
class ArchiveStorageSnapshot:
    documents: int
    parsed_documents: int
    elements: int
    element_text_bytes: int
    chunks: int
    embeddings: int


@dataclass(frozen=True, slots=True)
class ArchiveMetadataSummary:
    issuers: int
    filings_selected: int
    documents_created: int
    documents_updated: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ArchiveMaterializationSummary:
    selected: int
    downloaded: int
    downloaded_bytes: int
    already_materialized: int
    protected_existing: int
    parsed_documents: int
    parsed_elements: int
    documents_without_selected_sections: int
    latency_ms: int


def select_archive_issuers(
    session: Session,
    *,
    universe_code: str,
    period_from: date,
    period_to: date,
    include_provisional: bool = True,
    offset: int = 0,
    limit: int | None = None,
) -> list[ArchiveIssuer]:
    """Select issuer CIKs with any membership evidence overlapping the archive window."""

    if period_to < period_from:
        raise ValueError("period_to must not precede period_from")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    statuses = ("verified", "provisional") if include_provisional else ("verified",)
    statement = (
        select(Company.id, Company.cik, Company.name)
        .join(Security, Security.company_id == Company.id)
        .join(UniverseMembership, UniverseMembership.security_id == Security.id)
        .where(
            UniverseMembership.universe_code == universe_code.strip().lower(),
            UniverseMembership.verification_status.in_(statuses),
            UniverseMembership.effective_from <= period_to,
            (
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > period_from)
            ),
        )
        .distinct()
        .order_by(Company.cik, Company.id)
        .offset(offset)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return [
        ArchiveIssuer(company_id=int(row.id), cik=str(row.cik), name=str(row.name))
        for row in session.execute(statement)
    ]


def archive_storage_snapshot(
    session: Session,
    *,
    issuers: list[ArchiveIssuer],
    filed_from: date,
    filed_to: date,
    form_types: list[str],
) -> ArchiveStorageSnapshot:
    company_ids = [issuer.company_id for issuer in issuers]
    if not company_ids:
        return ArchiveStorageSnapshot(0, 0, 0, 0, 0, 0)
    document_filter = (
        Document.company_id.in_(company_ids),
        Document.form_type.in_([form.upper() for form in form_types]),
        Document.filing_date >= filed_from,
        Document.filing_date <= filed_to,
    )
    document_ids = select(Document.id).where(*document_filter)
    documents = session.scalar(
        select(func.count()).select_from(Document).where(*document_filter)
    ) or 0
    parsed_documents = session.scalar(
        select(func.count(func.distinct(DocumentElement.document_id))).where(
            DocumentElement.document_id.in_(document_ids)
        )
    ) or 0
    elements = session.scalar(
        select(func.count()).select_from(DocumentElement).where(
            DocumentElement.document_id.in_(document_ids)
        )
    ) or 0
    text_bytes = session.scalar(
        select(
            func.coalesce(
                func.sum(
                    func.length(func.coalesce(DocumentElement.text, ""))
                    + func.length(func.coalesce(DocumentElement.markdown, ""))
                ),
                0,
            )
        ).where(DocumentElement.document_id.in_(document_ids))
    ) or 0
    chunks = session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id.in_(document_ids))
    ) or 0
    embeddings = session.scalar(
        select(func.count())
        .select_from(Embedding)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .where(Chunk.document_id.in_(document_ids))
    ) or 0
    return ArchiveStorageSnapshot(
        documents=int(documents),
        parsed_documents=int(parsed_documents),
        elements=int(elements),
        element_text_bytes=int(text_bytes),
        chunks=int(chunks),
        embeddings=int(embeddings),
    )


def ingest_archive_metadata(
    session: Session,
    *,
    client: SECClient,
    issuers: list[ArchiveIssuer],
    form_types: list[str],
    filed_from: date,
    filed_to: date,
    limit_per_form: int | None = None,
) -> ArchiveMetadataSummary:
    """Upsert historical filing metadata by stable CIK, committing after each issuer."""

    started = perf_counter()
    selected = created = updated = 0
    for issuer in issuers:
        company = session.get(Company, issuer.company_id)
        if company is None or company.cik != issuer.cik:
            raise ValueError(f"archive issuer changed during run: {issuer.cik}")
        filings = client.list_filings(
            issuer.cik,
            form_types,
            filed_from=filed_from,
            filed_to=filed_to,
            limit=limit_per_form,
        )
        selected += len(filings)
        for filing in filings:
            accession = str(filing["accession_number"])
            document = session.scalar(
                select(Document).where(
                    Document.company_id == company.id,
                    Document.accession_number == accession,
                )
            )
            is_new = document is None
            if document is None:
                document = Document(
                    company=company,
                    source_type="sec",
                    form_type=str(filing["form_type"]),
                    accession_number=accession,
                )
                session.add(document)
            _update_archive_document(document, issuer.cik, filing)
            if is_new:
                created += 1
            else:
                updated += 1
        session.commit()
    return ArchiveMetadataSummary(
        issuers=len(issuers),
        filings_selected=selected,
        documents_created=created,
        documents_updated=updated,
        latency_ms=round((perf_counter() - started) * 1000),
    )


def materialize_archive_filings(
    session: Session,
    *,
    downloader: SECFilingDownloader,
    parser: HtmlFilingParser,
    issuers: list[ArchiveIssuer],
    form_types: list[str],
    filed_from: date,
    filed_to: date,
    sections: tuple[str, ...] = DEFAULT_ARCHIVE_SECTIONS,
    force_parse: bool = False,
) -> ArchiveMaterializationSummary:
    """Download and retain only research sections; never create chunks or embeddings."""

    started = perf_counter()
    company_ids = [issuer.company_id for issuer in issuers]
    documents = list(
        session.scalars(
            select(Document)
            .options(joinedload(Document.company))
            .where(
                Document.company_id.in_(company_ids),
                Document.form_type.in_([form.upper() for form in form_types]),
                Document.filing_date >= filed_from,
                Document.filing_date <= filed_to,
            )
            .order_by(Document.company_id, Document.filing_date, Document.accession_number)
        ).unique()
    )
    downloaded = downloaded_bytes = already = protected = parsed = parsed_elements = empty = 0
    for document in documents:
        metadata = dict(document.metadata_json or {})
        archive_metadata = metadata.get("research_archive")
        if (
            not force_parse
            and isinstance(archive_metadata, dict)
            and archive_metadata.get("profile") == ARCHIVE_PROFILE
            and archive_metadata.get("sha256_hash") == document.sha256_hash
            and archive_metadata.get("sections") == list(sections)
        ):
            already += 1
            continue
        has_chunks = session.scalar(
            select(Chunk.id).where(Chunk.document_id == document.id).limit(1)
        ) is not None
        has_selected_elements = session.scalar(
            select(DocumentElement.id)
            .where(
                DocumentElement.document_id == document.id,
                DocumentElement.section.in_(sections),
            )
            .limit(1)
        ) is not None
        if has_chunks or (has_selected_elements and not force_parse):
            protected += 1
            continue
        primary_document = _primary_document(document)
        result = downloader.download(
            cik=document.company.cik,
            accession_number=document.accession_number,
            primary_document=primary_document,
            expected_sha256=document.sha256_hash,
        )
        if result.downloaded:
            downloaded += 1
            downloaded_bytes += result.size_bytes
        selected_elements = [
            element
            for element in parser.parse_file(result.local_path)
            if element.section in sections
        ]
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
                for element in selected_elements
            ]
        )
        document.sha256_hash = result.sha256_hash
        document.local_path = None
        metadata["research_archive"] = {
            "profile": ARCHIVE_PROFILE,
            "sections": list(sections),
            "sha256_hash": result.sha256_hash,
            "source_size_bytes": result.size_bytes,
            "selected_element_count": len(selected_elements),
        }
        document.metadata_json = metadata
        parsed += 1
        parsed_elements += len(selected_elements)
        if not selected_elements:
            empty += 1
        session.commit()
    return ArchiveMaterializationSummary(
        selected=len(documents),
        downloaded=downloaded,
        downloaded_bytes=downloaded_bytes,
        already_materialized=already,
        protected_existing=protected,
        parsed_documents=parsed,
        parsed_elements=parsed_elements,
        documents_without_selected_sections=empty,
        latency_ms=round((perf_counter() - started) * 1000),
    )


def export_archive_panel(
    session: Session,
    *,
    issuers: list[ArchiveIssuer],
    filed_from: date,
    filed_to: date,
    output_path: Path,
) -> dict[str, Any]:
    """Export archive risk-change features with exact source lineage to Parquet."""

    started = perf_counter()
    panel = build_research_panel(
        session,
        ResearchPanelQuery(
            ciks=[issuer.cik for issuer in issuers],
            period_end_from=filed_from,
            period_end_to=filed_to,
            as_of=datetime.combine(filed_to, time.max, tzinfo=UTC),
            form_types=["10-K"],
            sections=list(DEFAULT_ARCHIVE_SECTIONS),
            features=["risk_changes"],
            limit=10_000,
        ),
    )
    write_research_panel(output_path, panel, output_format="parquet")
    return {
        "path": str(output_path),
        "rows": len(panel.rows),
        "corpus_snapshot_id": panel.corpus_snapshot_id,
        "feature_version": panel.feature_version,
        "size_bytes": output_path.stat().st_size,
        "latency_ms": round((perf_counter() - started) * 1000),
    }


def archive_report_payload(
    *,
    universe_code: str,
    period_from: date,
    period_to: date,
    issuers: list[ArchiveIssuer],
    before: ArchiveStorageSnapshot,
    after: ArchiveStorageSnapshot | None = None,
    metadata: ArchiveMetadataSummary | None = None,
    materialization: ArchiveMaterializationSummary | None = None,
    panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_after = after or before
    return {
        "schema_version": ARCHIVE_PROFILE,
        "universe_code": universe_code,
        "period_from": period_from.isoformat(),
        "period_to": period_to.isoformat(),
        "issuer_count": len(issuers),
        "issuers": [asdict(issuer) for issuer in issuers],
        "storage_before": asdict(before),
        "storage_after": asdict(resolved_after),
        "storage_delta": {
            field: getattr(resolved_after, field) - getattr(before, field)
            for field in ArchiveStorageSnapshot.__dataclass_fields__
        },
        "metadata": asdict(metadata) if metadata is not None else None,
        "materialization": asdict(materialization) if materialization is not None else None,
        "panel": panel,
        "cost_guardrail": {
            "new_recurring_services": [],
            "provider_calls": {"embeddings": 0, "generation": 0, "reranking": 0},
            "estimated_provider_cost_usd": 0,
            "normal_monthly_target_usd": "10-15",
            "hard_ceiling_usd": 20,
        },
        "invariants": {
            "accession_and_availability_required": True,
            "bulk_embeddings_disabled": True,
            "embedding_rows_unchanged": before.embeddings == resolved_after.embeddings,
            "sections": list(DEFAULT_ARCHIVE_SECTIONS),
        },
    }


def write_archive_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _update_archive_document(document: Document, cik: str, filing: dict[str, Any]) -> None:
    primary_document = str(filing["primary_document"])
    filing_date = _parse_date(filing.get("filing_date"))
    accepted_at = _parse_datetime(filing.get("acceptance_datetime"))
    document.source_type = "sec"
    document.form_type = str(filing["form_type"])
    document.filing_date = filing_date
    document.period_end_date = _parse_date(filing.get("report_date"))
    document.accepted_at = accepted_at
    document.available_at = accepted_at or (
        datetime.combine(filing_date, time.max, tzinfo=UTC) if filing_date else None
    )
    document.is_amendment = document.form_type.upper().endswith("/A")
    document.primary_document_url = build_primary_document_url(
        cik,
        document.accession_number,
        primary_document,
    )
    document.source_url = company_submissions_url(cik)
    metadata = dict(document.metadata_json or {})
    metadata.update(
        {
            key: value
            for key, value in filing.items()
            if key not in {"accession_number", "filing_date", "form_type", "report_date"}
            and value is not None
            and value != ""
        }
    )
    metadata["archive_metadata_profile"] = ARCHIVE_PROFILE
    document.metadata_json = metadata


def _primary_document(document: Document) -> str:
    metadata = document.metadata_json or {}
    primary_document = metadata.get("primary_document")
    if isinstance(primary_document, str) and primary_document:
        return primary_document
    if document.primary_document_url:
        return Path(document.primary_document_url).name
    raise ValueError(f"Document {document.accession_number} has no primary document filename")


def _parse_date(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
