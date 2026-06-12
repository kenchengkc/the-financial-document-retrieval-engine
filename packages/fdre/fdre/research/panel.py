from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Company, Document, DocumentElement, FinancialFact
from fdre.ingestion.xbrl import CANONICAL_CONCEPTS
from fdre.research.filing_diffs import diff_documents, select_comparable_document

FEATURE_VERSION = "fdre-panel-v1"
PanelFeature = Literal[
    "filing_length",
    "section_novelty",
    "risk_changes",
    "document_density",
    "topic_mentions",
    "filing_timing",
    "xbrl_growth",
    "xbrl_margins",
]
ExportFormat = Literal["json", "csv", "parquet"]
TOPIC_PATTERNS = {
    "ai": re.compile(r"\b(?:artificial intelligence|generative ai|machine learning)\b", re.I),
    "climate": re.compile(r"\b(?:climate|carbon|greenhouse gas|emissions)\b", re.I),
    "cybersecurity": re.compile(r"\b(?:cybersecurity|cyber attack|data breach)\b", re.I),
    "supply_chain": re.compile(r"\b(?:supply chain|supplier|sourcing)\b", re.I),
    "regulation": re.compile(r"\b(?:regulation|regulatory|compliance)\b", re.I),
    "competition": re.compile(r"\b(?:competition|competitive|competitor)\b", re.I),
}


class ResearchPanelQuery(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    period_end_from: date | None = None
    period_end_to: date | None = None
    as_of: datetime | None = None
    form_types: list[str] = Field(default_factory=lambda: ["10-K", "10-Q"])
    sections: list[str] = Field(default_factory=list)
    features: list[PanelFeature] = Field(default_factory=list)
    include_amendments: bool = False
    limit: int = Field(default=1000, ge=1, le=10_000)


class ResearchPanelRow(BaseModel):
    ticker: str
    cik: str
    accession_number: str
    form_type: str
    period_end: date | None
    accepted_at: datetime | None
    available_at: datetime
    is_amendment: bool
    filing_length_tokens: int | None = None
    filing_length_characters: int | None = None
    section_token_counts: dict[str, int] = Field(default_factory=dict)
    section_novelty: dict[str, float] = Field(default_factory=dict)
    risk_added_passages: int | None = None
    risk_removed_passages: int | None = None
    table_density: float | None = None
    numeric_density: float | None = None
    topic_mentions: dict[str, int] = Field(default_factory=dict)
    filing_delay_days: int | None = None
    amendment_indicator: int | None = None
    revenue_growth: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    capex_to_revenue: float | None = None
    operating_cash_flow_to_revenue: float | None = None
    source_accessions: list[str]
    feature_provenance: dict[str, list[str]]
    calculation_version: str
    corpus_snapshot_id: str
    max_source_available_at: datetime


class ResearchPanel(BaseModel):
    query: ResearchPanelQuery
    feature_version: str
    corpus_snapshot_id: str
    rows: list[ResearchPanelRow]


def build_research_panel(
    session: Session,
    query: ResearchPanelQuery,
) -> ResearchPanel:
    statement = (
        select(Document)
        .join(Company, Company.id == Document.company_id)
        .where(
            Document.available_at.is_not(None),
            Document.period_end_date.is_not(None),
        )
        .order_by(Document.available_at, Document.id)
    )
    if query.tickers:
        statement = statement.where(
            Company.ticker.in_([ticker.upper() for ticker in query.tickers])
        )
    if query.form_types:
        statement = statement.where(
            Document.form_type.in_([form.upper() for form in query.form_types])
        )
    if query.period_end_from:
        statement = statement.where(Document.period_end_date >= query.period_end_from)
    if query.period_end_to:
        statement = statement.where(Document.period_end_date <= query.period_end_to)
    if query.as_of:
        statement = statement.where(Document.available_at <= query.as_of)
    if not query.include_amendments:
        statement = statement.where(Document.is_amendment.is_(False))
    documents = list(session.scalars(statement.limit(query.limit)))
    snapshot_id = _corpus_snapshot_id(documents)
    rows = [
        _build_row(session, document, query=query, snapshot_id=snapshot_id)
        for document in documents
    ]
    validate_point_in_time_rows(rows)
    return ResearchPanel(
        query=query,
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id=snapshot_id,
        rows=rows,
    )


def write_research_panel(
    path: str | Path,
    panel: ResearchPanel,
    *,
    output_format: ExportFormat,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content, _ = serialize_research_panel(panel, output_format=output_format)
    destination.write_bytes(content)
    return destination


def serialize_research_panel(
    panel: ResearchPanel,
    *,
    output_format: ExportFormat,
) -> tuple[bytes, str]:
    records = [_export_record(row) for row in panel.rows]
    if output_format == "json":
        return (
            (json.dumps(records, indent=2, default=str) + "\n").encode(),
            "application/json",
        )
    if output_format == "csv":
        output = io.StringIO(newline="")
        fieldnames = list(records[0]) if records else list(ResearchPanelRow.model_fields)
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
        return output.getvalue().encode(), "text/csv"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError(
            "Parquet export requires `pip install -e '.[data]'`."
        ) from error
    sink = pa.BufferOutputStream()
    pq.write_table(  # type: ignore[no-untyped-call]
        pa.Table.from_pylist(records),
        sink,
    )
    return sink.getvalue().to_pybytes(), "application/vnd.apache.parquet"


def validate_point_in_time_rows(rows: list[ResearchPanelRow]) -> None:
    for row in rows:
        if row.max_source_available_at > row.available_at:
            raise ValueError(
                f"Point-in-time leakage for {row.accession_number}: "
                f"source available {row.max_source_available_at.isoformat()} "
                f"after row {row.available_at.isoformat()}"
            )


def _build_row(
    session: Session,
    document: Document,
    *,
    query: ResearchPanelQuery,
    snapshot_id: str,
) -> ResearchPanelRow:
    available_at = _required_datetime(document.available_at)
    selected_features = set(query.features) or {
        "filing_length",
        "section_novelty",
        "risk_changes",
        "document_density",
        "topic_mentions",
        "filing_timing",
        "xbrl_growth",
        "xbrl_margins",
    }
    elements = list(
        session.scalars(
            select(DocumentElement)
            .where(DocumentElement.document_id == document.id)
            .order_by(DocumentElement.reading_order, DocumentElement.id)
        )
    )
    texts_by_section = _texts_by_section(elements, query.sections)
    all_text = " ".join(text for texts in texts_by_section.values() for text in texts)
    prior, _ = select_comparable_document(session, document, as_of=available_at)
    source_documents = [document, *([prior] if prior is not None else [])]
    source_accessions = [source.accession_number for source in source_documents]
    source_times = [
        _required_datetime(source.available_at)
        for source in source_documents
        if source.available_at is not None
    ]
    prior_sections = (
        _texts_by_section(
            list(
                session.scalars(
                    select(DocumentElement)
                    .where(DocumentElement.document_id == prior.id)
                    .order_by(DocumentElement.reading_order, DocumentElement.id)
                )
            ),
            query.sections,
        )
        if prior is not None
        else {}
    )
    current_facts = _fact_values(session, document.id, available_at)
    prior_facts = (
        _fact_values(session, prior.id, available_at) if prior is not None else {}
    )
    fact_times = [
        fact.available_at
        for fact in session.scalars(
            select(FinancialFact).where(
                FinancialFact.document_id.in_(
                    [source.id for source in source_documents]
                ),
                FinancialFact.available_at <= available_at,
            )
        )
        if fact.available_at is not None
    ]
    source_times.extend(fact_times)
    diff = (
        diff_documents(
            session,
            prior,
            document,
            comparison_basis="research_panel_comparable",
        )
        if prior is not None and "risk_changes" in selected_features
        else None
    )
    revenue = current_facts.get("revenue")
    previous_revenue = prior_facts.get("revenue")
    return ResearchPanelRow(
        ticker=document.company.ticker,
        cik=document.company.cik,
        accession_number=document.accession_number,
        form_type=document.form_type,
        period_end=document.period_end_date,
        accepted_at=document.accepted_at,
        available_at=available_at,
        is_amendment=document.is_amendment,
        filing_length_tokens=(
            len(all_text.split()) if "filing_length" in selected_features else None
        ),
        filing_length_characters=(
            len(all_text) if "filing_length" in selected_features else None
        ),
        section_token_counts=(
            {section: len(" ".join(texts).split()) for section, texts in texts_by_section.items()}
            if "filing_length" in selected_features
            else {}
        ),
        section_novelty=(
            _section_novelty(texts_by_section, prior_sections)
            if "section_novelty" in selected_features
            else {}
        ),
        risk_added_passages=(
            _risk_change_count(diff, "added") if diff is not None else None
        ),
        risk_removed_passages=(
            _risk_change_count(diff, "removed") if diff is not None else None
        ),
        table_density=(
            sum(element.element_type == "table" for element in elements)
            / max(len(elements), 1)
            if "document_density" in selected_features
            else None
        ),
        numeric_density=(
            sum(character.isdigit() for character in all_text) / max(len(all_text), 1)
            if "document_density" in selected_features
            else None
        ),
        topic_mentions=(
            {
                topic: len(pattern.findall(all_text))
                for topic, pattern in TOPIC_PATTERNS.items()
            }
            if "topic_mentions" in selected_features
            else {}
        ),
        filing_delay_days=(
            (available_at.date() - document.period_end_date).days
            if "filing_timing" in selected_features and document.period_end_date
            else None
        ),
        amendment_indicator=(
            int(document.is_amendment)
            if "filing_timing" in selected_features
            else None
        ),
        revenue_growth=(
            _growth(revenue, previous_revenue)
            if "xbrl_growth" in selected_features
            else None
        ),
        operating_margin=(
            _ratio(current_facts.get("operating_income"), revenue)
            if "xbrl_margins" in selected_features
            else None
        ),
        net_margin=(
            _ratio(current_facts.get("net_income"), revenue)
            if "xbrl_margins" in selected_features
            else None
        ),
        capex_to_revenue=(
            _ratio(current_facts.get("capex"), revenue)
            if "xbrl_margins" in selected_features
            else None
        ),
        operating_cash_flow_to_revenue=(
            _ratio(current_facts.get("operating_cash_flow"), revenue)
            if "xbrl_margins" in selected_features
            else None
        ),
        source_accessions=source_accessions,
        feature_provenance={
            "filing_features": [document.accession_number],
            "comparison_features": (
                [document.accession_number, prior.accession_number]
                if prior is not None
                else [document.accession_number]
            ),
            "xbrl_features": source_accessions,
        },
        calculation_version=FEATURE_VERSION,
        corpus_snapshot_id=snapshot_id,
        max_source_available_at=max(source_times, default=available_at),
    )


def _texts_by_section(
    elements: list[DocumentElement],
    selected_sections: list[str],
) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    wanted = set(selected_sections)
    for element in elements:
        section = element.section or "Unsectioned"
        if wanted and section not in wanted:
            continue
        text = (element.markdown if element.element_type == "table" else element.text) or ""
        normalized = " ".join(text.split())
        if normalized:
            sections.setdefault(section, []).append(normalized)
    return sections


def _section_novelty(
    current: dict[str, list[str]],
    previous: dict[str, list[str]],
) -> dict[str, float]:
    novelty: dict[str, float] = {}
    for section, passages in current.items():
        current_fingerprints = {_text_fingerprint(passage) for passage in passages}
        previous_fingerprints = {
            _text_fingerprint(passage) for passage in previous.get(section, [])
        }
        novelty[section] = (
            1.0
            - len(current_fingerprints & previous_fingerprints)
            / max(len(current_fingerprints), 1)
        )
    return novelty


def _fact_values(
    session: Session,
    document_id: int,
    as_of: datetime,
) -> dict[str, Decimal]:
    facts = list(
        session.scalars(
            select(FinancialFact).where(
                FinancialFact.document_id == document_id,
                FinancialFact.canonical_metric.is_not(None),
                FinancialFact.value.is_not(None),
                FinancialFact.available_at <= as_of,
            )
        )
    )
    selected: dict[str, tuple[int, Decimal]] = {}
    for fact in facts:
        metric = fact.canonical_metric
        if metric is None or fact.value is None:
            continue
        concepts = CANONICAL_CONCEPTS.get(metric, ())
        priority = concepts.index(fact.concept) if fact.concept in concepts else len(concepts)
        existing = selected.get(metric)
        if existing is None or priority < existing[0]:
            selected[metric] = (priority, fact.value)
    return {metric: value for metric, (_, value) in selected.items()}


def _growth(current: Decimal | None, previous: Decimal | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return float((current - previous) / abs(previous))


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator / denominator)


def _risk_change_count(
    difference: Any,
    change_type: str,
) -> int:
    return sum(
        change.change_type == change_type and change.section == "Risk Factors"
        for change in difference.changes
    )


def _text_fingerprint(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def _corpus_snapshot_id(documents: list[Document]) -> str:
    payload = "|".join(
        f"{document.accession_number}:{document.sha256_hash or ''}"
        for document in documents
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _required_datetime(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("Point-in-time panel requires document availability timestamps")
    return value


def _export_record(row: ResearchPanelRow) -> dict[str, Any]:
    record = row.model_dump(mode="json")
    for key, value in list(record.items()):
        if isinstance(value, (dict, list)):
            record[key] = json.dumps(value, sort_keys=True)
    return record
