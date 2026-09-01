from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, joinedload

from apps.api.app.models import Company, Document, DocumentElement, FinancialFact
from fdre.ingestion.xbrl import CANONICAL_CONCEPTS
from fdre.research.filing_diffs import select_comparable_document_from_candidates

PanelFeature = Literal[
    "filing_length",
    "section_novelty",
    "disclosure_similarity",
    "risk_changes",
    "document_density",
    "topic_mentions",
    "filing_timing",
    "xbrl_growth",
    "xbrl_margins",
]
ExportFormat = Literal["json", "csv", "parquet"]
FEATURE_VERSION = "fdre-panel-v3"
PANEL_FEATURE_ORDER: tuple[PanelFeature, ...] = (
    "filing_length",
    "section_novelty",
    "disclosure_similarity",
    "risk_changes",
    "document_density",
    "topic_mentions",
    "filing_timing",
    "xbrl_growth",
    "xbrl_margins",
)
DEFAULT_PANEL_FEATURES: tuple[PanelFeature, ...] = (
    "filing_length",
    "section_novelty",
    "risk_changes",
    "document_density",
    "topic_mentions",
    "filing_timing",
    "xbrl_growth",
    "xbrl_margins",
)
_FEATURE_CALCULATION_VERSIONS: dict[PanelFeature, str] = {
    "filing_length": "filing-length-v1",
    "section_novelty": "section-novelty-v1",
    "disclosure_similarity": "disclosure-similarity-v1",
    "risk_changes": "risk-changes-v1",
    "document_density": "document-density-v1",
    "topic_mentions": "topic-mentions-v1",
    "filing_timing": "filing-timing-v1",
    "xbrl_growth": "xbrl-growth-v1",
    "xbrl_margins": "xbrl-margins-v1",
}
_COMPARISON_FEATURES: frozenset[PanelFeature] = frozenset(
    {
        "section_novelty",
        "disclosure_similarity",
        "risk_changes",
        "xbrl_growth",
    }
)
_SECTION_PARAMETER_FEATURES: frozenset[PanelFeature] = frozenset(
    {
        "filing_length",
        "section_novelty",
        "disclosure_similarity",
        "risk_changes",
        "document_density",
        "topic_mentions",
    }
)
_FEATURE_FACT_METRICS: dict[PanelFeature, frozenset[str]] = {
    "xbrl_growth": frozenset({"revenue"}),
    "xbrl_margins": frozenset(
        {
            "revenue",
            "operating_income",
            "net_income",
            "capex",
            "operating_cash_flow",
        }
    ),
}
TOPIC_PATTERNS = {
    "ai": re.compile(r"\b(?:artificial intelligence|generative ai|machine learning)\b", re.I),
    "climate": re.compile(r"\b(?:climate|carbon|greenhouse gas|emissions)\b", re.I),
    "cybersecurity": re.compile(r"\b(?:cybersecurity|cyber attack|data breach)\b", re.I),
    "supply_chain": re.compile(r"\b(?:supply chain|supplier|sourcing)\b", re.I),
    "regulation": re.compile(r"\b(?:regulation|regulatory|compliance)\b", re.I),
    "competition": re.compile(r"\b(?:competition|competitive|competitor)\b", re.I),
}


@dataclass(frozen=True, slots=True)
class PanelElement:
    document_id: int
    element_type: str
    section: str | None
    text: str | None
    markdown: str | None


@dataclass(frozen=True, slots=True)
class PanelFact:
    document_id: int
    canonical_metric: str | None
    concept: str
    value: Decimal | None
    available_at: datetime | None


@dataclass(frozen=True, slots=True)
class RiskChangeMetrics:
    added: int
    removed: int
    current_passages: int
    previous_passages: int

    @property
    def churn_rate(self) -> float:
        return (self.added + self.removed) / max(
            self.current_passages + self.previous_passages,
            1,
        )


class FeatureLineage(BaseModel):
    feature: PanelFeature
    calculation_version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_accessions: list[str]
    source_available_at: dict[str, datetime]
    max_source_available_at: datetime
    corpus_snapshot_id: str
    lineage_id: str = Field(min_length=64, max_length=64)


class ResearchPanelQuery(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    ciks: list[str] = Field(default_factory=list)
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
    disclosure_similarity: float | None = None
    risk_added_passages: int | None = None
    risk_removed_passages: int | None = None
    risk_current_passages: int | None = None
    risk_previous_passages: int | None = None
    risk_churn_rate: float | None = None
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
    feature_lineage: dict[PanelFeature, FeatureLineage] = Field(default_factory=dict)
    calculation_version: str
    corpus_snapshot_id: str
    max_source_available_at: datetime


class ResearchPanel(BaseModel):
    query: ResearchPanelQuery
    feature_version: str
    corpus_snapshot_id: str
    rows: list[ResearchPanelRow]


def empty_research_panel(query: ResearchPanelQuery) -> ResearchPanel:
    """Return the canonical empty panel without executing an unfiltered document query."""

    return ResearchPanel(
        query=query,
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id=_corpus_snapshot_id([]),
        rows=[],
    )


def build_research_panel(
    session: Session,
    query: ResearchPanelQuery,
    *,
    timings_ms: dict[str, int] | None = None,
    latest_with_priors_only: bool = False,
) -> ResearchPanel:
    db_checkout_started = perf_counter()
    session.connection()
    _record_timing(timings_ms, "panel_db_checkout", db_checkout_started)

    document_select_started = perf_counter()
    statement = (
        select(Document)
        .options(contains_eager(Document.company))
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
    if query.ciks:
        statement = statement.where(Company.cik.in_(query.ciks))
    if not query.tickers and not query.ciks:
        statement = statement.where(Company.ticker.is_not(None))
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
    documents = list(session.scalars(statement.limit(query.limit)).unique())
    _record_timing(timings_ms, "panel_document_select", document_select_started)
    if not documents:
        return empty_research_panel(query)

    history_pool_started = perf_counter()
    company_ids = {document.company_id for document in documents}
    document_pool = list(
        session.scalars(
            select(Document)
            .options(joinedload(Document.company))
            .where(Document.company_id.in_(company_ids))
        ).unique()
    )
    documents_by_company: dict[int, list[Document]] = defaultdict(list)
    for document in document_pool:
        documents_by_company[document.company_id].append(document)
    _record_timing(timings_ms, "panel_history_pool", history_pool_started)

    prior_resolution_started = perf_counter()
    prior_by_document: dict[int, Document | None] = {}
    source_documents_by_id = {document.id: document for document in documents}
    for document in documents:
        prior, _ = select_comparable_document_from_candidates(
            document,
            documents_by_company[document.company_id],
            as_of=_required_datetime(document.available_at),
        )
        prior_by_document[document.id] = prior
        if prior is not None:
            source_documents_by_id[prior.id] = prior
    _record_timing(timings_ms, "panel_prior_resolution", prior_resolution_started)

    snapshot_started = perf_counter()
    source_document_ids = set(source_documents_by_id)
    snapshot_id = _corpus_snapshot_id(list(source_documents_by_id.values()))
    _record_timing(timings_ms, "panel_snapshot", snapshot_started)
    selected_features = set(query.features or DEFAULT_PANEL_FEATURES)

    row_documents = documents
    element_source_ids = source_document_ids
    fact_source_ids = source_document_ids
    if latest_with_priors_only:
        row_documents = _latest_documents_with_priors(documents, prior_by_document)
        row_document_ids = {document.id for document in row_documents}
        element_source_ids = set(row_document_ids)
        fact_source_ids = set(row_document_ids)
        if selected_features & (_COMPARISON_FEATURES & _SECTION_PARAMETER_FEATURES):
            element_source_ids.update(
                prior.id
                for document in row_documents
                if (prior := prior_by_document[document.id]) is not None
            )
        if "xbrl_growth" in selected_features:
            fact_source_ids.update(
                prior.id
                for document in row_documents
                if (prior := prior_by_document[document.id]) is not None
            )

    element_load_started = perf_counter()
    elements_by_document = (
        _load_panel_elements(session, element_source_ids)
        if selected_features & _SECTION_PARAMETER_FEATURES
        else {}
    )
    _record_timing(timings_ms, "panel_element_load", element_load_started)
    fact_load_started = perf_counter()
    facts_by_document = (
        _load_panel_facts(session, fact_source_ids)
        if any(feature in _FEATURE_FACT_METRICS for feature in selected_features)
        else {}
    )
    _record_timing(timings_ms, "panel_fact_load", fact_load_started)
    row_build_started = perf_counter()
    rows = [
        _build_row(
            document,
            query=query,
            snapshot_id=snapshot_id,
            prior=prior_by_document[document.id],
            elements_by_document=elements_by_document,
            facts_by_document=facts_by_document,
        )
        for document in row_documents
    ]
    validate_point_in_time_rows(rows)
    _record_timing(timings_ms, "panel_row_build", row_build_started)
    return ResearchPanel(
        query=query,
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id=snapshot_id,
        rows=rows,
    )


def _latest_documents_with_priors(
    documents: list[Document],
    prior_by_document: dict[int, Document | None],
) -> list[Document]:
    """Materialize only each issuer's latest PIT filing and its selected prior.

    The full eligible document set is still used for corpus snapshot identity and
    prior selection. This only prunes expensive feature loading and row construction.
    """
    latest_by_company: dict[int, Document] = {}
    for document in documents:
        incumbent = latest_by_company.get(document.company_id)
        if (
            incumbent is None
            or _document_filing_sort_key(document)
            > _document_filing_sort_key(incumbent)
        ):
            latest_by_company[document.company_id] = document

    selected_document_ids = {document.id for document in documents}
    materialized_ids: set[int] = set()
    for document in latest_by_company.values():
        materialized_ids.add(document.id)
        prior = prior_by_document[document.id]
        if prior is not None and prior.id in selected_document_ids:
            materialized_ids.add(prior.id)
    return [document for document in documents if document.id in materialized_ids]


def _document_filing_sort_key(document: Document) -> tuple[date, datetime, str]:
    return (
        document.period_end_date or date.min,
        _required_datetime(document.available_at),
        document.accession_number,
    )


def _record_timing(
    timings_ms: dict[str, int] | None,
    name: str,
    started: float,
) -> None:
    if timings_ms is not None:
        timings_ms[name] = round((perf_counter() - started) * 1000)


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
    pq.write_table(  # type: ignore[no-untyped-call, unused-ignore]
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
        for feature, lineage in row.feature_lineage.items():
            if lineage.feature != feature:
                raise ValueError(
                    f"Feature lineage key mismatch for {row.accession_number}: "
                    f"{feature} != {lineage.feature}"
                )
            if set(lineage.source_accessions) != set(lineage.source_available_at):
                raise ValueError(
                    f"Feature lineage sources incomplete for {row.accession_number}: "
                    f"{feature}"
                )
            if any(
                accession not in row.source_accessions
                for accession in lineage.source_accessions
            ):
                raise ValueError(
                    f"Feature lineage references an unknown source for "
                    f"{row.accession_number}: {feature}"
                )
            expected_max = max(
                lineage.source_available_at.values(),
                default=row.available_at,
            )
            if lineage.max_source_available_at != expected_max:
                raise ValueError(
                    f"Feature lineage availability mismatch for "
                    f"{row.accession_number}: {feature}"
                )
            if lineage.max_source_available_at > row.available_at:
                raise ValueError(
                    f"Point-in-time feature leakage for {row.accession_number}: "
                    f"{feature} source available "
                    f"{lineage.max_source_available_at.isoformat()} after row "
                    f"{row.available_at.isoformat()}"
                )
            expected_lineage_id = _feature_lineage_id(
                feature=lineage.feature,
                calculation_version=lineage.calculation_version,
                parameters=lineage.parameters,
                source_accessions=lineage.source_accessions,
                source_available_at=lineage.source_available_at,
                corpus_snapshot_id=lineage.corpus_snapshot_id,
            )
            if lineage.lineage_id != expected_lineage_id:
                raise ValueError(
                    f"Feature lineage hash mismatch for {row.accession_number}: "
                    f"{feature}"
                )


def _load_panel_elements(
    session: Session,
    document_ids: set[int],
) -> dict[int, list[PanelElement]]:
    grouped: dict[int, list[PanelElement]] = defaultdict(list)
    rows = session.execute(
        select(
            DocumentElement.document_id,
            DocumentElement.element_type,
            DocumentElement.section,
            DocumentElement.text,
            DocumentElement.markdown,
        )
        .where(DocumentElement.document_id.in_(document_ids))
        .order_by(
            DocumentElement.document_id,
            DocumentElement.reading_order,
            DocumentElement.id,
        )
    )
    for document_id, element_type, section, text, markdown in rows:
        grouped[document_id].append(
            PanelElement(
                document_id=document_id,
                element_type=element_type,
                section=section,
                text=text,
                markdown=markdown,
            )
        )
    return dict(grouped)


def _load_panel_facts(
    session: Session,
    document_ids: set[int],
) -> dict[int, list[PanelFact]]:
    grouped: dict[int, list[PanelFact]] = defaultdict(list)
    rows = session.execute(
        select(
            FinancialFact.document_id,
            FinancialFact.canonical_metric,
            FinancialFact.concept,
            FinancialFact.value,
            FinancialFact.available_at,
        ).where(FinancialFact.document_id.in_(document_ids))
    )
    for document_id, canonical_metric, concept, value, available_at in rows:
        if document_id is None:
            continue
        grouped[document_id].append(
            PanelFact(
                document_id=document_id,
                canonical_metric=canonical_metric,
                concept=concept,
                value=value,
                available_at=available_at,
            )
        )
    return dict(grouped)


def _build_row(
    document: Document,
    *,
    query: ResearchPanelQuery,
    snapshot_id: str,
    prior: Document | None,
    elements_by_document: dict[int, list[PanelElement]],
    facts_by_document: dict[int, list[PanelFact]],
) -> ResearchPanelRow:
    available_at = _required_datetime(document.available_at)
    selected_features: set[PanelFeature] = set(query.features or DEFAULT_PANEL_FEATURES)
    elements = elements_by_document.get(document.id, [])
    texts_by_section = _texts_by_section(elements, query.sections)
    all_text = " ".join(text for texts in texts_by_section.values() for text in texts)
    source_documents = [document, *([prior] if prior is not None else [])]
    source_accessions = [source.accession_number for source in source_documents]
    prior_sections = (
        _texts_by_section(
            elements_by_document.get(prior.id, []),
            query.sections,
        )
        if prior is not None
        else {}
    )
    current_facts = _fact_values(
        facts_by_document.get(document.id, []),
        available_at,
    )
    prior_facts = (
        _fact_values(facts_by_document.get(prior.id, []), available_at)
        if prior is not None
        else {}
    )
    risk_change = (
        _risk_factor_changes(texts_by_section, prior_sections)
        if prior is not None and "risk_changes" in selected_features
        else None
    )
    revenue = current_facts.get("revenue")
    previous_revenue = prior_facts.get("revenue")
    feature_lineage = {
        feature: _build_feature_lineage(
            feature,
            document=document,
            prior=prior,
            selected_sections=query.sections,
            row_available_at=available_at,
            facts_by_document=facts_by_document,
            snapshot_id=snapshot_id,
        )
        for feature in PANEL_FEATURE_ORDER
        if feature in selected_features
    }
    return ResearchPanelRow(
        ticker=_required_company_ticker(document),
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
            {
                section: len(" ".join(texts).split())
                for section, texts in texts_by_section.items()
            }
            if "filing_length" in selected_features
            else {}
        ),
        section_novelty=(
            _section_novelty(texts_by_section, prior_sections)
            if "section_novelty" in selected_features
            else {}
        ),
        disclosure_similarity=(
            _disclosure_similarity(texts_by_section, prior_sections)
            if "disclosure_similarity" in selected_features
            else None
        ),
        risk_added_passages=risk_change.added if risk_change is not None else None,
        risk_removed_passages=risk_change.removed if risk_change is not None else None,
        risk_current_passages=(
            risk_change.current_passages if risk_change is not None else None
        ),
        risk_previous_passages=(
            risk_change.previous_passages if risk_change is not None else None
        ),
        risk_churn_rate=risk_change.churn_rate if risk_change is not None else None,
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
        feature_lineage=feature_lineage,
        calculation_version=FEATURE_VERSION,
        corpus_snapshot_id=snapshot_id,
        max_source_available_at=max(
            (
                lineage.max_source_available_at
                for lineage in feature_lineage.values()
            ),
            default=available_at,
        ),
    )


def _build_feature_lineage(
    feature: PanelFeature,
    *,
    document: Document,
    prior: Document | None,
    selected_sections: list[str],
    row_available_at: datetime,
    facts_by_document: dict[int, list[PanelFact]],
    snapshot_id: str,
) -> FeatureLineage:
    source_documents = [document]
    if feature in _COMPARISON_FEATURES and prior is not None:
        source_documents.append(prior)
    parameters: dict[str, Any] = {}
    if feature in _SECTION_PARAMETER_FEATURES:
        parameters["sections"] = list(selected_sections)

    fact_metrics = _FEATURE_FACT_METRICS.get(feature, frozenset())
    source_available_at: dict[str, datetime] = {}
    for source in source_documents:
        source_time = _required_datetime(source.available_at)
        if fact_metrics:
            relevant_fact_times = [
                fact.available_at
                for fact in facts_by_document.get(source.id, [])
                if fact.canonical_metric in fact_metrics
                and fact.available_at is not None
                and fact.available_at <= row_available_at
            ]
            source_time = max(
                [source_time, *relevant_fact_times],
            )
        source_available_at[source.accession_number] = source_time

    source_accessions = [source.accession_number for source in source_documents]
    calculation_version = _FEATURE_CALCULATION_VERSIONS[feature]
    lineage_id = _feature_lineage_id(
        feature=feature,
        calculation_version=calculation_version,
        parameters=parameters,
        source_accessions=source_accessions,
        source_available_at=source_available_at,
        corpus_snapshot_id=snapshot_id,
    )
    return FeatureLineage(
        feature=feature,
        calculation_version=calculation_version,
        parameters=parameters,
        source_accessions=source_accessions,
        source_available_at=source_available_at,
        max_source_available_at=max(
            source_available_at.values(),
            default=row_available_at,
        ),
        corpus_snapshot_id=snapshot_id,
        lineage_id=lineage_id,
    )


def _feature_lineage_id(
    *,
    feature: PanelFeature,
    calculation_version: str,
    parameters: dict[str, Any],
    source_accessions: list[str],
    source_available_at: dict[str, datetime],
    corpus_snapshot_id: str,
) -> str:
    payload = json.dumps(
        {
            "feature": feature,
            "calculation_version": calculation_version,
            "parameters": parameters,
            "source_accessions": source_accessions,
            "source_available_at": {
                accession: source_available_at[accession].isoformat()
                for accession in sorted(source_available_at)
            },
            "corpus_snapshot_id": corpus_snapshot_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _texts_by_section(
    elements: list[PanelElement],
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


def _disclosure_similarity(
    current: dict[str, list[str]],
    previous: dict[str, list[str]],
) -> float | None:
    """Document-level Jaccard similarity of passage fingerprints vs the prior
    comparable filing (the "Lazy Prices" disclosure-change measure). 1.0 means
    the filing is textually unchanged; lower means more revised. Point-in-time
    safe: the prior filing is strictly older than ``available_at``."""
    if not previous:
        return None
    current_fingerprints = {
        _text_fingerprint(passage) for passages in current.values() for passage in passages
    }
    previous_fingerprints = {
        _text_fingerprint(passage) for passages in previous.values() for passage in passages
    }
    union = current_fingerprints | previous_fingerprints
    if not union:
        return None
    return len(current_fingerprints & previous_fingerprints) / len(union)


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
    facts: list[PanelFact],
    as_of: datetime,
) -> dict[str, Decimal]:
    selected: dict[str, tuple[int, Decimal]] = {}
    for fact in facts:
        metric = fact.canonical_metric
        if (
            metric is None
            or fact.value is None
            or fact.available_at is None
            or fact.available_at > as_of
        ):
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


def _risk_factor_changes(
    current: dict[str, list[str]],
    previous: dict[str, list[str]],
) -> RiskChangeMetrics:
    """Measure two-sided Item 1A passage churn versus the comparable filing."""
    current_risk = {
        _text_fingerprint(passage) for passage in current.get("Risk Factors", [])
    }
    previous_risk = {
        _text_fingerprint(passage) for passage in previous.get("Risk Factors", [])
    }
    return RiskChangeMetrics(
        added=len(current_risk - previous_risk),
        removed=len(previous_risk - current_risk),
        current_passages=len(current_risk),
        previous_passages=len(previous_risk),
    )


def _text_fingerprint(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def _corpus_snapshot_id(documents: list[Document]) -> str:
    payload = json.dumps(
        [
            {
                "accession_number": document.accession_number,
                "available_at": (
                    document.available_at.isoformat()
                    if document.available_at is not None
                    else None
                ),
                "form_type": document.form_type,
                "period_end": (
                    document.period_end_date.isoformat()
                    if document.period_end_date is not None
                    else None
                ),
                "sha256_hash": document.sha256_hash or "",
            }
            for document in sorted(documents, key=lambda item: item.accession_number)
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _required_datetime(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("Point-in-time panel requires document availability timestamps")
    return value


def _required_company_ticker(document: Document) -> str:
    ticker = document.company.ticker
    return ticker if ticker is not None else f"CIK:{document.company.cik}"


def _export_record(row: ResearchPanelRow) -> dict[str, Any]:
    record = row.model_dump(mode="json")
    for key, value in list(record.items()):
        if isinstance(value, (dict, list)):
            record[key] = json.dumps(value, sort_keys=True)
    return record
