"""Point-in-time acceleration in comparable-filing Risk Factors language churn."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fdre.research.experiments.event_study import FilingEvent
from fdre.research.panel import FeatureLineage, ResearchPanelRow
from fdre.research.signals.composite import (
    CompositeEvent,
    SignalComponent,
    period_label,
    standardize_by_period,
)

RISK_CHURN_SIGNAL_NAME = "risk_factor_churn_acceleration"
RISK_CHURN_ACCELERATION_VERSION = "risk-churn-acceleration-v1"
RISK_CHURN_NEUTRALIZATION_VERSION = "period-sector-v1"
RISK_CHURN_ACCELERATION_DEFINITION: dict[str, object] = {
    "signal": RISK_CHURN_SIGNAL_NAME,
    "raw_formula": (
        "current comparable-filing risk_churn_rate minus the selected prior "
        "comparable filing's risk_churn_rate"
    ),
    "research_score": "negative raw acceleration",
    "directional_hypothesis": (
        "accelerating Risk Factors language churn predicts lower subsequent "
        "benchmark-adjusted equity returns"
    ),
    "source_feature": "risk_changes",
    "source_feature_version": "risk-changes-v1",
    "calculation_version": RISK_CHURN_ACCELERATION_VERSION,
}


def build_risk_churn_acceleration_events(
    rows: list[ResearchPanelRow],
) -> list[FilingEvent]:
    """Build a higher-is-better expected-return score with full PIT lineage.

    The selected prior comes from the current row's ``risk_changes`` lineage,
    not from chronological adjacency. The prior filing must itself have a
    ``risk_changes`` lineage, so the derived feature usually binds current,
    prior, and prior-prior source filings.
    """
    by_accession = {row.accession_number: row for row in rows}
    events: list[FilingEvent] = []
    for row in sorted(rows, key=lambda item: (item.available_at, item.accession_number)):
        if row.risk_churn_rate is None:
            continue
        current_lineage = row.feature_lineage.get("risk_changes")
        if current_lineage is None:
            continue
        prior_accession = _selected_prior_accession(row, current_lineage)
        if prior_accession is None:
            continue
        prior_row = by_accession.get(prior_accession)
        if prior_row is None or prior_row.risk_churn_rate is None:
            continue
        prior_lineage = prior_row.feature_lineage.get("risk_changes")
        if prior_lineage is None:
            continue
        source_accessions, source_available_at = _merged_sources(
            current_lineage,
            prior_lineage,
        )
        if current_lineage.corpus_snapshot_id != prior_lineage.corpus_snapshot_id:
            raise ValueError(
                f"risk-churn lineage snapshot mismatch for {row.accession_number}"
            )
        max_source_available_at = max(source_available_at.values())
        if max_source_available_at > row.available_at:
            raise ValueError(
                f"risk-churn acceleration leakage for {row.accession_number}: "
                "a source filing was not available at the event decision time"
            )
        raw_acceleration = float(row.risk_churn_rate) - float(prior_row.risk_churn_rate)
        # Predeclared directional score: higher means less acceleration / more
        # deceleration, matching the expected-return long-side convention.
        score = -raw_acceleration
        parameters = dict(RISK_CHURN_ACCELERATION_DEFINITION)
        lineage_id = _lineage_id(
            parameters=parameters,
            source_accessions=source_accessions,
            source_available_at=source_available_at,
            corpus_snapshot_id=current_lineage.corpus_snapshot_id,
        )
        feature_lineage = FeatureLineage(
            feature="risk_changes",
            calculation_version=RISK_CHURN_ACCELERATION_VERSION,
            parameters=parameters,
            source_accessions=source_accessions,
            source_available_at=source_available_at,
            max_source_available_at=max_source_available_at,
            corpus_snapshot_id=current_lineage.corpus_snapshot_id,
            lineage_id=lineage_id,
        )
        events.append(
            FilingEvent(
                ticker=row.ticker.upper(),
                accession_number=row.accession_number,
                available_at=row.available_at,
                max_source_available_at=max_source_available_at,
                feature_value=score,
                feature_lineage=feature_lineage,
            )
        )
    return events


def neutralize_risk_churn_events(
    events: list[FilingEvent],
    sector_by_ticker: dict[str, str],
    *,
    min_group: int = 4,
) -> list[FilingEvent]:
    """Apply the flagship's predeclared period/sector standardization deterministically."""

    composite_events = [
        CompositeEvent(
            ticker=event.ticker,
            accession_number=event.accession_number,
            available_at_period=period_label(event.available_at.date()),
            available_at=event.available_at,
            max_source_available_at=event.max_source_available_at,
            raw={RISK_CHURN_SIGNAL_NAME: float(event.feature_value)},
        )
        for event in events
        if event.feature_value is not None
    ]
    sector_by_accession = {
        event.accession_number: sector_by_ticker.get(event.ticker.upper(), "Unknown")
        for event in events
    }
    standardized = standardize_by_period(
        composite_events,
        [SignalComponent(name=RISK_CHURN_SIGNAL_NAME, sign=1)],
        sector_by_accession=sector_by_accession,
        min_group=min_group,
    )
    normalized: list[FilingEvent] = []
    for event in events:
        score = standardized.get(event.accession_number, {}).get(RISK_CHURN_SIGNAL_NAME)
        if score is None:
            continue
        normalized.append(event.model_copy(update={"feature_value": score}))
    return normalized


def build_neutralized_risk_churn_acceleration_events(
    rows: list[ResearchPanelRow],
    sector_by_ticker: dict[str, str],
    *,
    min_group: int = 4,
) -> list[FilingEvent]:
    """Rebuild the exact scored events consumed by the flagship walk-forward study."""

    return neutralize_risk_churn_events(
        build_risk_churn_acceleration_events(rows),
        sector_by_ticker,
        min_group=min_group,
    )


def _selected_prior_accession(
    row: ResearchPanelRow,
    lineage: FeatureLineage,
) -> str | None:
    return next(
        (
            accession
            for accession in lineage.source_accessions
            if accession != row.accession_number
        ),
        None,
    )


def _merged_sources(
    *lineages: FeatureLineage,
) -> tuple[list[str], dict[str, datetime]]:
    accessions: list[str] = []
    available_at: dict[str, datetime] = {}
    for lineage in lineages:
        for accession in lineage.source_accessions:
            source_time = lineage.source_available_at.get(accession)
            if source_time is None:
                raise ValueError(f"missing source availability for accession {accession}")
            existing = available_at.get(accession)
            if existing is not None and existing != source_time:
                raise ValueError(f"conflicting source availability for accession {accession}")
            if accession not in available_at:
                accessions.append(accession)
            available_at[accession] = source_time
    return accessions, available_at


def _lineage_id(
    *,
    parameters: dict[str, object],
    source_accessions: list[str],
    source_available_at: dict[str, datetime],
    corpus_snapshot_id: str,
) -> str:
    payload = {
        "feature": "risk_changes",
        "calculation_version": RISK_CHURN_ACCELERATION_VERSION,
        "parameters": parameters,
        "source_accessions": source_accessions,
        "source_available_at": {
            accession: source_available_at[accession].isoformat()
            for accession in source_accessions
        },
        "corpus_snapshot_id": corpus_snapshot_id,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
