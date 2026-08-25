from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.models import Company, Document, FinancialFact
from fdre.ingestion.sec_client import SECClient, company_facts_url

CANONICAL_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "debt": (
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
    ),
    "shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
}
CONCEPT_TO_METRIC = {
    concept: metric
    for metric, concepts in CANONICAL_CONCEPTS.items()
    for concept in concepts
}


@dataclass(frozen=True, slots=True)
class XBRLIngestionSummary:
    companies: int
    facts_seen: int
    facts_stored: int
    facts_skipped_without_document: int


def ingest_company_facts(
    session: Session,
    client: SECClient,
    *,
    tickers: Iterable[str] | None = None,
) -> XBRLIngestionSummary:
    statement = select(Company).order_by(Company.ticker)
    normalized_tickers = [ticker.upper() for ticker in tickers or []]
    if normalized_tickers:
        statement = statement.where(Company.ticker.in_(normalized_tickers))
    companies = list(session.scalars(statement))
    seen = 0
    stored = 0
    skipped = 0
    for company in companies:
        payload = client.get_company_facts(company.cik)
        facts, company_seen, company_skipped = normalize_company_facts(
            session,
            company,
            payload,
        )
        seen += company_seen
        skipped += company_skipped
        fact_keys = [fact.fact_key for fact in facts if fact.fact_key]
        if fact_keys:
            session.execute(
                delete(FinancialFact).where(FinancialFact.fact_key.in_(fact_keys))
            )
        session.add_all(facts)
        session.commit()
        stored += len(facts)
    return XBRLIngestionSummary(
        companies=len(companies),
        facts_seen=seen,
        facts_stored=stored,
        facts_skipped_without_document=skipped,
    )


def normalize_company_facts(
    session: Session,
    company: Company,
    payload: dict[str, Any],
) -> tuple[list[FinancialFact], int, int]:
    documents = {
        document.accession_number: document
        for document in session.scalars(
            select(Document).where(Document.company_id == company.id)
        )
    }
    facts_payload = payload.get("facts")
    if not isinstance(facts_payload, dict):
        return [], 0, 0
    facts_by_key: dict[str, FinancialFact] = {}
    seen = 0
    skipped = 0
    restatement_groups: dict[
        tuple[str, str, date | None, date | None],
        list[FinancialFact],
    ] = defaultdict(list)
    for taxonomy, taxonomy_payload in facts_payload.items():
        if not isinstance(taxonomy_payload, dict):
            continue
        for concept, concept_payload in taxonomy_payload.items():
            if not isinstance(concept_payload, dict):
                continue
            canonical_metric = (
                CONCEPT_TO_METRIC.get(concept) if taxonomy == "us-gaap" else None
            )
            units = concept_payload.get("units")
            if not isinstance(units, dict):
                continue
            for unit, unit_facts in units.items():
                if not isinstance(unit_facts, list):
                    continue
                normalized_unit = _normalize_unit(unit)
                for raw_fact in unit_facts:
                    if not isinstance(raw_fact, dict):
                        continue
                    seen += 1
                    accession = _string(raw_fact.get("accn"))
                    document = documents.get(accession or "")
                    if document is None:
                        skipped += 1
                        continue
                    value = _decimal(raw_fact.get("val"))
                    if value is None:
                        continue
                    period_start = _date(raw_fact.get("start"))
                    period_end = _date(raw_fact.get("end"))
                    fact_key = _fact_key(
                        company.cik,
                        taxonomy,
                        concept,
                        normalized_unit,
                        period_start,
                        period_end,
                        accession or "",
                        raw_fact.get("frame"),
                    )
                    fact = FinancialFact(
                        company=company,
                        document=document,
                        ticker=company.ticker,
                        fact_key=fact_key,
                        taxonomy=taxonomy,
                        concept=concept,
                        canonical_metric=canonical_metric,
                        label=_string(concept_payload.get("label")),
                        value=value,
                        unit=normalized_unit,
                        period_start=period_start,
                        period_end=period_end,
                        fiscal_year=_integer(raw_fact.get("fy")),
                        fiscal_period=_string(raw_fact.get("fp")),
                        period_type="duration" if period_start else "instant",
                        frame=_string(raw_fact.get("frame")),
                        form_type=_string(raw_fact.get("form")),
                        accession_number=accession,
                        filed_at=_date(raw_fact.get("filed")),
                        available_at=document.available_at,
                        is_amendment=str(raw_fact.get("form", "")).upper().endswith(
                            "/A"
                        ),
                        source_url=document.primary_document_url
                        or document.source_url
                        or company_facts_url(company.cik),
                        metadata_json={
                            "raw_fact": raw_fact,
                            "description": concept_payload.get("description"),
                        },
                    )
                    facts_by_key[fact_key] = fact
                    restatement_groups[
                        (f"{taxonomy}:{concept}", normalized_unit, period_start, period_end)
                    ].append(fact)
    _mark_restatements(restatement_groups)
    facts = list(facts_by_key.values())
    return facts, seen, skipped


def _mark_restatements(
    groups: dict[
        tuple[str, str, date | None, date | None],
        list[FinancialFact],
    ],
) -> None:
    for group in groups.values():
        ordered = sorted(
            group,
            key=lambda fact: (
                fact.filed_at or date.min,
                fact.accession_number or "",
            ),
        )
        previous_value: Decimal | None = None
        for fact in ordered:
            fact.is_restatement = (
                previous_value is not None and fact.value != previous_value
            )
            previous_value = fact.value


def _fact_key(
    cik: str,
    taxonomy: str,
    concept: str,
    unit: str,
    period_start: date | None,
    period_end: date | None,
    accession: str,
    frame: object,
) -> str:
    payload = json.dumps(
        {
            "cik": cik,
            "taxonomy": taxonomy,
            "concept": concept,
            "unit": unit,
            "start": period_start.isoformat() if period_start else None,
            "end": period_end.isoformat() if period_end else None,
            "accession": accession,
            "frame": frame,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_unit(value: str) -> str:
    aliases = {
        "USD": "USD",
        "shares": "shares",
        "USD/shares": "USD/share",
        "pure": "ratio",
    }
    return aliases.get(value, value)


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
