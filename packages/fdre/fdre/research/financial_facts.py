from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, FinancialFact
from fdre.evals.datasets import EvidenceReference
from fdre.ingestion.xbrl import CANONICAL_CONCEPTS

CanonicalMetric = Literal[
    "revenue",
    "operating_income",
    "net_income",
    "eps",
    "cash",
    "debt",
    "shares",
    "capex",
    "operating_cash_flow",
]
RestatementPolicy = Literal["latest", "as_reported", "all"]


class FinancialFactQuery(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    metrics: list[CanonicalMetric] = Field(default_factory=list)
    period_end_from: date | None = None
    period_end_to: date | None = None
    as_of: datetime | None = None
    form_types: list[str] = Field(default_factory=list)
    restatement_policy: RestatementPolicy = "latest"
    limit: int = Field(default=100, ge=1, le=1000)


class FinancialFactRecord(BaseModel):
    ticker: str
    canonical_metric: CanonicalMetric
    concept: str
    label: str | None
    value: Decimal
    unit: str | None
    period_start: date | None
    period_end: date | None
    period_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    form_type: str | None
    accession_number: str
    filed_at: date | None
    available_at: datetime | None
    is_amendment: bool
    is_restatement: bool
    source_url: str | None
    narrative_evidence: EvidenceReference | None


class FinancialFactsResponse(BaseModel):
    query: FinancialFactQuery
    facts: list[FinancialFactRecord]


def query_financial_facts(
    session: Session,
    query: FinancialFactQuery,
) -> FinancialFactsResponse:
    statement = (
        select(FinancialFact)
        .where(
            FinancialFact.canonical_metric.is_not(None),
            FinancialFact.document_id.is_not(None),
            FinancialFact.value.is_not(None),
            FinancialFact.accession_number.is_not(None),
        )
        .order_by(
            FinancialFact.period_end.desc(),
            FinancialFact.available_at.desc(),
            FinancialFact.id.desc(),
        )
    )
    if query.tickers:
        statement = statement.where(
            FinancialFact.ticker.in_([ticker.upper() for ticker in query.tickers])
        )
    if query.metrics:
        statement = statement.where(FinancialFact.canonical_metric.in_(query.metrics))
    if query.period_end_from:
        statement = statement.where(FinancialFact.period_end >= query.period_end_from)
    if query.period_end_to:
        statement = statement.where(FinancialFact.period_end <= query.period_end_to)
    if query.as_of:
        statement = statement.where(FinancialFact.available_at <= query.as_of)
    if query.form_types:
        statement = statement.where(
            FinancialFact.form_type.in_([form.upper() for form in query.form_types])
        )

    candidates = list(session.scalars(statement.limit(query.limit * 4)))
    selected = _apply_restatement_policy(candidates, query.restatement_policy)[: query.limit]
    evidence_by_document = _load_narrative_evidence(
        session,
        [fact.document_id for fact in selected if fact.document_id is not None],
    )
    records = [
        FinancialFactRecord(
            ticker=fact.ticker,
            canonical_metric=_canonical_metric(fact.canonical_metric),
            concept=fact.concept,
            label=fact.label,
            value=_required_decimal(fact.value),
            unit=fact.unit,
            period_start=fact.period_start,
            period_end=fact.period_end,
            period_type=fact.period_type,
            fiscal_year=fact.fiscal_year,
            fiscal_period=fact.fiscal_period,
            form_type=fact.form_type,
            accession_number=_required_string(fact.accession_number),
            filed_at=fact.filed_at,
            available_at=fact.available_at,
            is_amendment=fact.is_amendment,
            is_restatement=fact.is_restatement,
            source_url=fact.source_url,
            narrative_evidence=(
                evidence_by_document.get(fact.document_id)
                if fact.document_id is not None
                else None
            ),
        )
        for fact in selected
    ]
    return FinancialFactsResponse(query=query, facts=records)


def _apply_restatement_policy(
    facts: list[FinancialFact],
    policy: RestatementPolicy,
) -> list[FinancialFact]:
    if policy == "all":
        return facts
    selected: dict[
        tuple[str, str | None, str, str | None, date | None, date | None],
        FinancialFact,
    ] = {}
    for fact in facts:
        key = (
            fact.ticker,
            fact.canonical_metric,
            fact.concept,
            fact.unit,
            fact.period_start,
            fact.period_end,
        )
        existing = selected.get(key)
        if existing is None:
            selected[key] = fact
            continue
        existing_order = (existing.filed_at or date.min, existing.id)
        fact_order = (fact.filed_at or date.min, fact.id)
        should_replace = (
            policy == "latest" and fact_order > existing_order
        ) or (
            policy == "as_reported" and fact_order < existing_order
        )
        if should_replace:
            selected[key] = fact
    return list(selected.values())


def _load_narrative_evidence(
    session: Session,
    document_ids: list[int],
) -> dict[int, EvidenceReference]:
    if not document_ids:
        return {}
    chunks = session.scalars(
        select(Chunk)
        .where(Chunk.document_id.in_(set(document_ids)))
        .order_by(Chunk.document_id, Chunk.id)
    )
    evidence: dict[int, EvidenceReference] = {}
    for chunk in chunks:
        if chunk.document_id in evidence or len(chunk.chunk_text.split()) < 5:
            continue
        metadata = chunk.metadata_json or {}
        accession = metadata.get("accession_number")
        if not isinstance(accession, str):
            accession = chunk.document.accession_number
        evidence[chunk.document_id] = EvidenceReference.from_quote(
            accession_number=accession,
            section=chunk.section,
            quote=chunk.chunk_text,
            ticker=metadata.get("ticker") if isinstance(metadata.get("ticker"), str) else None,
        )
    return evidence


def _canonical_metric(value: str | None) -> CanonicalMetric:
    if value not in CANONICAL_CONCEPTS:
        raise ValueError(f"Unsupported canonical metric {value!r}")
    return value  # type: ignore[return-value]


def _required_decimal(value: Decimal | None) -> Decimal:
    if value is None:
        raise ValueError("Financial fact has no numeric value")
    return value


def _required_string(value: str | None) -> str:
    if value is None:
        raise ValueError("Financial fact has no accession number")
    return value
