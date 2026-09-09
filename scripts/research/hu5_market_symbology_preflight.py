"""Validate frozen HU-5 market symbology and cache coverage without scoring returns."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.composite_study import (
    CompositeEvent,
    SignalComponent,
    period_label,
    standardize_by_period,
)
from fdre.research.experiments.event_study import EventStudyConfig, EventWindow, FilingEvent
from fdre.research.hu5_multiclass import (
    HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
    market_symbols_for_events,
    resolve_hu5_events_multiclass,
)
from fdre.research.hu5_universe import (
    build_hu5_universe_gate,
    load_hu5_universe_records,
    select_historical_issuer_ciks,
)
from fdre.research.market_data import DEFAULT_CACHE_DIR
from fdre.research.market_symbology import (
    HU5_MARKET_SYMBOLOGY_MANIFEST_ID,
    HU5_MARKET_SYMBOLOGY_SCHEMA_VERSION,
    assert_frozen_hu5_market_symbology_manifest,
    fetch_hu5_market_bars,
    hu5_market_symbology_manifest_payload,
    hu5_provider_symbol,
    validate_hu5_market_alias_windows,
)
from fdre.research.panel import ResearchPanelQuery, build_research_panel
from fdre.research.risk_churn_acceleration import build_risk_churn_acceleration_events

SIGNAL_NAME = "risk_factor_churn_acceleration"
UNIVERSE_CODE = "sp500"
RESEARCH_WINDOW_START = date(2010, 1, 1)
RESEARCH_WINDOW_END = date(2026, 9, 1)
FORWARD_BUFFER_DAYS = 230
MAX_ISSUERS = 250
MIN_DOCUMENTS = 6
BENCHMARK = "SPY"
EXPECTED_STRICT_ELIGIBLE_DAYS = 6088
EXPECTED_GATE_MANIFEST_ID = "95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8"
EXPECTED_OUTCOME_MAPPING_ID = "17c668c61da943beb48c9f3dd58325ab7222bb3836d21774eacfa07b0f704cd2"
EXPECTED_RESOLVED_EVENT_COUNT = 3996
EXPECTED_MULTICLASS_EVENT_COUNT = 14
EXPECTED_MARKET_START = date(2012, 1, 16)
EXPECTED_MARKET_END = date(2027, 4, 19)
EXPECTED_COMPONENT_SYMBOL_COUNT = 270
EXPECTED_REQUIRED_HISTORICAL_SYMBOL_COUNT = 271


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the frozen HU-5 provider-symbol contract and cache coverage. "
            "No returns, folds, diagnostics, or promotion decisions are computed."
        )
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    return parser


def _event_config() -> EventStudyConfig:
    return EventStudyConfig(
        benchmark_ticker=BENCHMARK,
        windows=[
            EventWindow(start=1, end=21),
            EventWindow(start=1, end=63),
            EventWindow(start=1, end=126),
        ],
        bootstrap_iterations=2000,
        random_seed=17,
    )


def _neutralize_events(
    events: list[FilingEvent],
    sector_by_accession: dict[str, str],
) -> list[FilingEvent]:
    composite_events = [
        CompositeEvent(
            ticker=event.ticker,
            accession_number=event.accession_number,
            available_at_period=period_label(event.available_at.date()),
            available_at=event.available_at,
            max_source_available_at=event.max_source_available_at,
            raw={SIGNAL_NAME: float(event.feature_value)},
        )
        for event in events
        if event.feature_value is not None
    ]
    standardized = standardize_by_period(
        composite_events,
        [SignalComponent(name=SIGNAL_NAME, sign=1)],
        sector_by_accession={
            event.accession_number: sector_by_accession.get(
                event.accession_number, "Unknown"
            )
            for event in events
        },
        min_group=4,
    )
    normalized: list[FilingEvent] = []
    for event in events:
        score = standardized.get(event.accession_number, {}).get(SIGNAL_NAME)
        if score is not None:
            normalized.append(event.model_copy(update={"feature_value": score}))
    return normalized


def _assert_frozen_state(
    *,
    strict_eligible_days: int,
    gate_manifest_id: str,
    outcome_mapping_id: str,
    resolved_event_count: int,
    multiclass_event_count: int,
    market_start: date,
    market_end: date,
    component_symbol_count: int,
    required_historical_symbol_count: int,
) -> None:
    observed = {
        "strict_eligible_days": strict_eligible_days,
        "gate_manifest_id": gate_manifest_id,
        "outcome_mapping_id": outcome_mapping_id,
        "resolved_event_count": resolved_event_count,
        "multiclass_event_count": multiclass_event_count,
        "market_start": market_start,
        "market_end": market_end,
        "component_symbol_count": component_symbol_count,
        "required_historical_symbol_count": required_historical_symbol_count,
    }
    expected = {
        "strict_eligible_days": EXPECTED_STRICT_ELIGIBLE_DAYS,
        "gate_manifest_id": EXPECTED_GATE_MANIFEST_ID,
        "outcome_mapping_id": EXPECTED_OUTCOME_MAPPING_ID,
        "resolved_event_count": EXPECTED_RESOLVED_EVENT_COUNT,
        "multiclass_event_count": EXPECTED_MULTICLASS_EVENT_COUNT,
        "market_start": EXPECTED_MARKET_START,
        "market_end": EXPECTED_MARKET_END,
        "component_symbol_count": EXPECTED_COMPONENT_SYMBOL_COUNT,
        "required_historical_symbol_count": EXPECTED_REQUIRED_HISTORICAL_SYMBOL_COUNT,
    }
    drift = {
        key: {"expected": str(expected[key]), "observed": str(value)}
        for key, value in observed.items()
        if value != expected[key]
    }
    if drift:
        raise RuntimeError(
            "frozen HU-5 market symbology preflight state drifted: "
            + json.dumps(drift, sort_keys=True)
        )


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def main() -> int:
    args = _parser().parse_args()
    assert_frozen_hu5_market_symbology_manifest()
    event_config = _event_config()

    with Session(create_db_engine()) as session:
        records = load_hu5_universe_records(
            session,
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
        )
        gate = build_hu5_universe_gate(
            records,
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
        )
        ciks, sector_by_cik = select_historical_issuer_ciks(
            session,
            universe_code=UNIVERSE_CODE,
            window_start=RESEARCH_WINDOW_START,
            window_end=RESEARCH_WINDOW_END,
            max_issuers=MAX_ISSUERS,
            min_documents=MIN_DOCUMENTS,
        )
        panel = build_research_panel(
            session,
            ResearchPanelQuery(
                ciks=ciks,
                period_end_from=RESEARCH_WINDOW_START,
                period_end_to=RESEARCH_WINDOW_END,
                form_types=["10-K", "10-Q"],
                features=["risk_changes"],
                limit=10_000,
            ),
        )
        cik_by_accession = {row.accession_number: row.cik for row in panel.rows}
        sector_by_accession = {
            row.accession_number: sector_by_cik.get(row.cik, "Unknown")
            for row in panel.rows
        }
        resolved = resolve_hu5_events_multiclass(
            build_risk_churn_acceleration_events(panel.rows),
            cik_by_accession=cik_by_accession,
            records=records,
            gate=gate,
        )

    if resolved.unresolved_accessions:
        raise RuntimeError(
            "frozen HU-5 outcome mapping became unresolved before symbology preflight: "
            + ",".join(resolved.unresolved_accessions)
        )
    events = _neutralize_events(list(resolved.events), sector_by_accession)
    if not events:
        raise RuntimeError("frozen HU-5 event set is empty")

    market_start = min(event.available_at.date() for event in events) - timedelta(days=10)
    market_end = max(event.available_at.date() for event in events) + timedelta(
        days=FORWARD_BUFFER_DAYS
    )
    component_symbols = market_symbols_for_events(events, resolved.outcome_mappings)
    required_historical_symbols = sorted({BENCHMARK, *component_symbols})
    _assert_frozen_state(
        strict_eligible_days=gate.strict_eligible_day_count,
        gate_manifest_id=gate.gate_manifest_id,
        outcome_mapping_id=resolved.outcome_mapping_id,
        resolved_event_count=len(resolved.events),
        multiclass_event_count=resolved.multiclass_event_count,
        market_start=market_start,
        market_end=market_end,
        component_symbol_count=len(component_symbols),
        required_historical_symbol_count=len(required_historical_symbols),
    )

    bars, missing = fetch_hu5_market_bars(
        component_symbols,
        market_start,
        market_end,
        benchmark=BENCHMARK,
        cache_dir=Path(args.cache_dir),
        cache_only=True,
        max_uncached_fetches=0,
    )
    if missing:
        raise RuntimeError(
            "HU-5 market symbology cache preflight is incomplete: "
            + ",".join(sorted(missing))
        )

    validate_hu5_market_alias_windows(
        events,
        resolved.outcome_mappings,
        bars,
        event_config,
    )

    provider_symbols = sorted(
        {hu5_provider_symbol(symbol) for symbol in required_historical_symbols}
    )
    payload: dict[str, object] = {
        "schema_version": "fdre-hu5-market-symbology-preflight-v1",
        "status": "PASS",
        "purpose": "market_symbology_cache_preflight_no_return_evaluation",
        "market_symbology_version": HU5_MARKET_SYMBOLOGY_SCHEMA_VERSION,
        "market_symbology_manifest_id": HU5_MARKET_SYMBOLOGY_MANIFEST_ID,
        "market_symbology_manifest": hu5_market_symbology_manifest_payload(),
        "issuer_outcome_policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "gate_manifest_id": gate.gate_manifest_id,
        "outcome_mapping_id": resolved.outcome_mapping_id,
        "strict_eligible_day_count": gate.strict_eligible_day_count,
        "resolved_event_count": len(resolved.events),
        "multiclass_event_count": resolved.multiclass_event_count,
        "component_symbol_count": len(component_symbols),
        "required_historical_symbol_count": len(required_historical_symbols),
        "provider_symbol_count": len(provider_symbols),
        "provider_symbols": provider_symbols,
        "market_start": market_start.isoformat(),
        "market_end": market_end.isoformat(),
        "cache_only": True,
        "missing_historical_symbols": [],
        "restricted_alias_window_validation": "PASS",
        "return_evaluation_performed": False,
    }
    payload["preflight_id"] = _stable_digest(payload)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print("HU5_MARKET_SYMBOLOGY_PREFLIGHT=PASS")
    print("HU5_MARKET_SYMBOLOGY_PREFLIGHT_JSON=" + json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
