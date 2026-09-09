"""Versioned HU-5 issuer-to-outcome mapping for multi-class issuers.

The policy implemented here is frozen in
``docs/research/historical-universe/multiclass-outcome-policy-v1.md``.
It intentionally leaves the original HU-5 resolver and unchanged flagship path
available at their historical commits while giving the amended rerun an explicit
policy identity.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from fdre.research.event_study import (
    EventReturn,
    EventStudyConfig,
    FilingEvent,
    MarketBar,
    run_event_study,
    validate_event_inputs,
)
from fdre.research.experiments.walk_forward import (
    WalkForwardConfig,
    WalkForwardObservation,
    WalkForwardStudyReport,
    build_walk_forward_folds,
    market_data_version,
)
from fdre.research.historical_universe import UniverseSnapshot
from fdre.research.hu5_universe import (
    HU5EventUniverseLineage,
    HU5UniverseGate,
    HU5UniverseRecords,
    strict_hu5_snapshot,
)

HU5_MULTICLASS_OUTCOME_POLICY_VERSION = "fdre-hu5-multiclass-outcome-v1"
HU5_OUTCOME_MAPPING_SCHEMA_VERSION = "fdre-hu5-event-outcome-mapping-v1"
HU5_AMENDED_EVENT_LINEAGE_SCHEMA_VERSION = "fdre-hu5-event-universe-lineage-v2"


@dataclass(frozen=True, slots=True)
class HU5OutcomeComponent:
    security_id: int
    symbol: str
    membership_source_hash: str
    identity_source_hash: str


@dataclass(frozen=True, slots=True)
class HU5EventOutcomeMapping:
    accession_number: str
    as_of: str
    snapshot_id: str
    cik: str
    observation_ticker: str
    components: tuple[HU5OutcomeComponent, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.components)

    @property
    def is_multiclass(self) -> bool:
        return len(self.components) > 1


@dataclass(frozen=True, slots=True)
class HU5AmendedResolvedEvents:
    events: tuple[FilingEvent, ...]
    lineage: tuple[HU5EventUniverseLineage, ...]
    outcome_mappings: tuple[HU5EventOutcomeMapping, ...]
    outcome_mapping_id: str
    universe_lineage_id: str
    excluded_invalid_date: int
    excluded_not_member: int
    unresolved_accessions: tuple[str, ...]

    @property
    def multiclass_event_count(self) -> int:
        return sum(item.is_multiclass for item in self.outcome_mappings)


@dataclass(frozen=True, slots=True)
class HU5OutcomeAvailabilityIssue:
    accession_number: str
    window: str
    reason: str
    start_date: str | None
    end_date: str | None
    missing_symbols: tuple[str, ...]


class HU5MultiClassOutcomeUnavailableError(ValueError):
    """Raised before scoring when v1 cannot form every required class basket."""

    def __init__(self, issues: tuple[HU5OutcomeAvailabilityIssue, ...]) -> None:
        self.issues = issues
        super().__init__(
            f"{len(issues)} multi-class event/window outcomes are unavailable under "
            f"{HU5_MULTICLASS_OUTCOME_POLICY_VERSION}"
        )


def resolve_hu5_events_multiclass(
    events: list[FilingEvent],
    *,
    cik_by_accession: dict[str, str],
    records: HU5UniverseRecords,
    gate: HU5UniverseGate,
) -> HU5AmendedResolvedEvents:
    """Resolve one issuer observation while retaining every active share class.

    Single-class events preserve the historical symbol as their observation key.
    Multi-class events receive a stable issuer key so downstream portfolio and
    inference layers cannot count the component classes as separate issuers.
    """
    eligible_dates = {
        date.fromisoformat(item.as_of)
        for item in gate.dates
        if item.eligible
    }
    snapshot_cache: dict[date, UniverseSnapshot] = {}
    resolved: list[FilingEvent] = []
    lineage: list[HU5EventUniverseLineage] = []
    mappings: list[HU5EventOutcomeMapping] = []
    excluded_invalid_date = 0
    excluded_not_member = 0
    unresolved: list[str] = []

    for event in events:
        as_of = event.available_at.date()
        if as_of not in eligible_dates:
            excluded_invalid_date += 1
            continue
        cik = cik_by_accession.get(event.accession_number)
        if cik is None:
            unresolved.append(event.accession_number)
            continue
        snapshot = snapshot_cache.get(as_of)
        if snapshot is None:
            snapshot = strict_hu5_snapshot(
                records,
                universe_code=gate.universe_code,
                as_of=as_of,
            )
            snapshot_cache[as_of] = snapshot
        matches = sorted(
            (item for item in snapshot.constituents if item.cik == cik),
            key=lambda item: (item.security_id, item.symbol.upper()),
        )
        if not matches:
            excluded_not_member += 1
            continue
        symbols = tuple(item.symbol.upper() for item in matches)
        if len(set(symbols)) != len(symbols):
            unresolved.append(event.accession_number)
            continue

        observation_ticker = symbols[0] if len(matches) == 1 else f"CIK-{cik}"
        resolved.append(event.model_copy(update={"ticker": observation_ticker}))
        components = tuple(
            HU5OutcomeComponent(
                security_id=item.security_id,
                symbol=item.symbol.upper(),
                membership_source_hash=item.membership_source_hash,
                identity_source_hash=item.identity_source_hash,
            )
            for item in matches
        )
        mappings.append(
            HU5EventOutcomeMapping(
                accession_number=event.accession_number,
                as_of=as_of.isoformat(),
                snapshot_id=snapshot.snapshot_id,
                cik=cik,
                observation_ticker=observation_ticker,
                components=components,
            )
        )
        for item in matches:
            lineage.append(
                HU5EventUniverseLineage(
                    accession_number=event.accession_number,
                    as_of=as_of.isoformat(),
                    snapshot_id=snapshot.snapshot_id,
                    security_id=item.security_id,
                    cik=cik,
                    symbol=item.symbol.upper(),
                    membership_source_hash=item.membership_source_hash,
                    identity_source_hash=item.identity_source_hash,
                )
            )

    lineage.sort(key=lambda item: (item.as_of, item.accession_number, item.security_id))
    mappings.sort(key=lambda item: (item.as_of, item.accession_number, item.observation_ticker))
    mapping_payload = {
        "schema_version": HU5_OUTCOME_MAPPING_SCHEMA_VERSION,
        "policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "gate_manifest_id": gate.gate_manifest_id,
        "mappings": [asdict(item) for item in mappings],
    }
    outcome_mapping_id = _stable_digest(mapping_payload)
    lineage_payload = {
        "schema_version": HU5_AMENDED_EVENT_LINEAGE_SCHEMA_VERSION,
        "policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "gate_manifest_id": gate.gate_manifest_id,
        "outcome_mapping_id": outcome_mapping_id,
        "events": [asdict(item) for item in lineage],
    }
    return HU5AmendedResolvedEvents(
        events=tuple(resolved),
        lineage=tuple(lineage),
        outcome_mappings=tuple(mappings),
        outcome_mapping_id=outcome_mapping_id,
        universe_lineage_id=_stable_digest(lineage_payload),
        excluded_invalid_date=excluded_invalid_date,
        excluded_not_member=excluded_not_member,
        unresolved_accessions=tuple(sorted(set(unresolved))),
    )


def write_hu5_multiclass_lineage(
    path: str | Path,
    resolved: HU5AmendedResolvedEvents,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": HU5_AMENDED_EVENT_LINEAGE_SCHEMA_VERSION,
        "policy_version": HU5_MULTICLASS_OUTCOME_POLICY_VERSION,
        "outcome_mapping_id": resolved.outcome_mapping_id,
        "universe_lineage_id": resolved.universe_lineage_id,
        "event_count": len(resolved.events),
        "lineage_row_count": len(resolved.lineage),
        "multiclass_event_count": resolved.multiclass_event_count,
        "events": [asdict(item) for item in resolved.lineage],
        "outcome_mappings": [asdict(item) for item in resolved.outcome_mappings],
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination


def market_symbols_for_events(
    events: list[FilingEvent],
    mappings: tuple[HU5EventOutcomeMapping, ...],
) -> list[str]:
    mapping_by_accession = {item.accession_number: item for item in mappings}
    symbols: set[str] = set()
    for event in events:
        mapping = mapping_by_accession.get(event.accession_number)
        if mapping is None:
            raise ValueError(f"missing HU-5 outcome mapping for {event.accession_number}")
        symbols.update(mapping.symbols)
    return sorted(symbols)


def run_hu5_multiclass_walk_forward_signal_study(
    events: list[FilingEvent],
    bars: list[MarketBar],
    event_study_config: EventStudyConfig,
    walk_forward_config: WalkForwardConfig,
    mappings: tuple[HU5EventOutcomeMapping, ...],
    *,
    signal_name: str,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    definition: dict[str, object] | None = None,
) -> WalkForwardStudyReport:
    """Run sealed walk-forward evaluation with v1 multi-class issuer outcomes."""
    scored = [event for event in events if event.feature_value is not None]
    if not scored:
        raise ValueError("walk-forward signal study requires scored filing events")
    validate_event_inputs(scored)
    mapping_by_accession = {item.accession_number: item for item in mappings}
    for event in scored:
        mapping = mapping_by_accession.get(event.accession_number)
        if mapping is None:
            raise ValueError(f"missing HU-5 outcome mapping for {event.accession_number}")
        if event.ticker.upper() != mapping.observation_ticker.upper():
            raise ValueError(f"HU-5 outcome key mismatch for {event.accession_number}")

    base_config = event_study_config.model_copy(update={"walk_forward_splits": []})
    single_events = [
        event
        for event in scored
        if not mapping_by_accession[event.accession_number].is_multiclass
    ]
    returns: list[EventReturn] = []
    if single_events:
        single_report = run_event_study(
            single_events,
            bars,
            base_config,
            dataset_version=dataset_version,
            feature_version=feature_version,
            code_sha=code_sha,
        )
        returns.extend(single_report.observations)
    returns.extend(
        _multi_class_event_returns(
            scored,
            bars,
            base_config,
            mapping_by_accession,
        )
    )

    observations = _walk_forward_observations(
        scored,
        bars,
        returns,
        base_config,
        mapping_by_accession,
    )
    folds, oos = build_walk_forward_folds(observations, walk_forward_config)
    lineage_digest, lineage_complete = _feature_lineage_digest(scored)
    precommitted_definition = definition or {}
    manifest = {
        "signal_name": signal_name,
        "outcome_name": "abnormal_return",
        "selection_policy": "precommitted_signal_definition",
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "market_data_version": market_data_version(bars),
        "universe_snapshot_id": _universe_snapshot_id(scored),
        "feature_snapshot_id": _feature_snapshot_id(scored),
        "code_sha": code_sha,
        "definition": precommitted_definition,
        "feature_lineage_digest": lineage_digest,
        "event_study_config": base_config.model_dump(mode="json"),
        "walk_forward_config": walk_forward_config.model_dump(mode="json"),
        "folds": [
            {
                "fold_id": fold.fold_id,
                "status": fold.status,
                "definition": fold.definition.model_dump(mode="json"),
            }
            for fold in folds
        ],
    }
    experiment_key = _stable_digest(manifest)
    oos_accessions = {item.accession_number for item in oos}
    return WalkForwardStudyReport(
        experiment_key=experiment_key,
        signal_name=signal_name,
        dataset_version=dataset_version,
        feature_version=feature_version,
        market_data_version=market_data_version(bars),
        universe_snapshot_id=_universe_snapshot_id(scored),
        feature_snapshot_id=_feature_snapshot_id(scored),
        code_sha=code_sha,
        definition=precommitted_definition,
        feature_lineage_digest=lineage_digest,
        feature_lineage_complete=lineage_complete,
        event_study_config=base_config,
        walk_forward_config=walk_forward_config,
        fold_count=len(folds),
        eligible_fold_count=sum(fold.status == "eligible" for fold in folds),
        oos_event_count=len(oos_accessions),
        oos_observation_count=len(oos),
        folds=folds,
        oos_observations=oos,
    )


def _multi_class_event_returns(
    events: list[FilingEvent],
    bars: list[MarketBar],
    config: EventStudyConfig,
    mapping_by_accession: dict[str, HU5EventOutcomeMapping],
) -> list[EventReturn]:
    bars_by_ticker = _bars_by_ticker(bars)
    benchmark = bars_by_ticker.get(config.benchmark_ticker.upper(), [])
    if not benchmark:
        raise HU5MultiClassOutcomeUnavailableError(
            (
                HU5OutcomeAvailabilityIssue(
                    accession_number="*",
                    window="*",
                    reason="benchmark_market_data_unavailable",
                    start_date=None,
                    end_date=None,
                    missing_symbols=(config.benchmark_ticker.upper(),),
                ),
            )
        )
    benchmark_by_date = {item.date: item for item in benchmark}
    component_by_date = {
        ticker: {item.date: item for item in ticker_bars}
        for ticker, ticker_bars in bars_by_ticker.items()
    }
    outcomes: list[EventReturn] = []
    issues: list[HU5OutcomeAvailabilityIssue] = []

    for event in events:
        mapping = mapping_by_accession[event.accession_number]
        if not mapping.is_multiclass:
            continue
        event_index = _event_session_index(event.available_at, benchmark, config)
        if event_index is None:
            issues.append(
                HU5OutcomeAvailabilityIssue(
                    accession_number=event.accession_number,
                    window="*",
                    reason="event_session_unavailable",
                    start_date=None,
                    end_date=None,
                    missing_symbols=(),
                )
            )
            continue
        event_session = benchmark[event_index].date
        for window in config.windows:
            start_index = event_index + window.start
            end_index = event_index + window.end
            if start_index < 0 or end_index >= len(benchmark):
                issues.append(
                    HU5OutcomeAvailabilityIssue(
                        accession_number=event.accession_number,
                        window=window.label,
                        reason="benchmark_window_unavailable",
                        start_date=None,
                        end_date=None,
                        missing_symbols=(),
                    )
                )
                continue
            start_date = benchmark[start_index].date
            end_date = benchmark[end_index].date
            missing = tuple(
                symbol
                for symbol in mapping.symbols
                if start_date not in component_by_date.get(symbol, {})
                or end_date not in component_by_date.get(symbol, {})
            )
            if missing:
                issues.append(
                    HU5OutcomeAvailabilityIssue(
                        accession_number=event.accession_number,
                        window=window.label,
                        reason="component_endpoint_unavailable",
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        missing_symbols=tuple(sorted(missing)),
                    )
                )
                continue
            component_returns = [
                component_by_date[symbol][end_date].adjusted_close
                / component_by_date[symbol][start_date].adjusted_close
                - 1.0
                for symbol in mapping.symbols
            ]
            issuer_return = mean(component_returns)
            benchmark_return = (
                benchmark_by_date[end_date].adjusted_close
                / benchmark_by_date[start_date].adjusted_close
                - 1.0
            )
            outcomes.append(
                EventReturn(
                    ticker=event.ticker.upper(),
                    accession_number=event.accession_number,
                    event_session=event_session,
                    window=window.label,
                    asset_return=issuer_return,
                    benchmark_return=benchmark_return,
                    abnormal_return=issuer_return - benchmark_return,
                )
            )

    if issues:
        raise HU5MultiClassOutcomeUnavailableError(tuple(issues))
    return outcomes


def _walk_forward_observations(
    events: list[FilingEvent],
    bars: list[MarketBar],
    returns: list[EventReturn],
    config: EventStudyConfig,
    mapping_by_accession: dict[str, HU5EventOutcomeMapping],
) -> list[WalkForwardObservation]:
    events_by_accession = {event.accession_number: event for event in events}
    bars_by_ticker = _bars_by_ticker(bars)
    benchmark = bars_by_ticker.get(config.benchmark_ticker.upper(), [])
    end_offset_by_window = {window.label: window.end for window in config.windows}
    observations: list[WalkForwardObservation] = []

    for outcome in returns:
        event = events_by_accession.get(outcome.accession_number)
        mapping = mapping_by_accession.get(outcome.accession_number)
        if event is None or mapping is None or event.feature_value is None:
            continue
        ticker_bars = benchmark if mapping.is_multiclass else bars_by_ticker.get(
            outcome.ticker.upper(), []
        )
        event_index = next(
            (
                index
                for index, bar in enumerate(ticker_bars)
                if bar.date == outcome.event_session
            ),
            None,
        )
        end_offset = end_offset_by_window.get(outcome.window)
        if event_index is None or end_offset is None:
            continue
        end_index = event_index + end_offset
        if end_index < 0 or end_index >= len(ticker_bars):
            continue
        observations.append(
            WalkForwardObservation(
                ticker=outcome.ticker.upper(),
                accession_number=outcome.accession_number,
                event_session=outcome.event_session,
                window=outcome.window,
                window_end_session=ticker_bars[end_index].date,
                feature_value=event.feature_value,
                outcome_value=outcome.abnormal_return,
                available_at=event.available_at,
                max_source_available_at=event.max_source_available_at,
                feature_lineage_id=(
                    event.feature_lineage.lineage_id
                    if event.feature_lineage is not None
                    else None
                ),
            )
        )
    observations.sort(
        key=lambda item: (item.event_session, item.accession_number, item.window)
    )
    return observations


def _bars_by_ticker(bars: list[MarketBar]) -> dict[str, list[MarketBar]]:
    grouped: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.ticker.upper()].append(bar)
    for values in grouped.values():
        values.sort(key=lambda item: item.date)
    return grouped


def _event_session_index(
    available_at: datetime,
    bars: list[MarketBar],
    config: EventStudyConfig,
) -> int | None:
    timezone = ZoneInfo(config.market_timezone)
    localized = available_at.astimezone(timezone)
    target_date = localized.date()
    if localized.time() >= config.market_close:
        target_date += timedelta(days=1)
    return next((index for index, bar in enumerate(bars) if bar.date >= target_date), None)


def _feature_lineage_digest(events: list[FilingEvent]) -> tuple[str | None, bool]:
    complete = bool(events) and all(event.feature_lineage is not None for event in events)
    if not complete:
        return None, False
    pairs = sorted(
        (event.accession_number, event.feature_lineage.lineage_id)
        for event in events
        if event.feature_lineage is not None
    )
    return _stable_digest(pairs), True


def _feature_snapshot_id(events: list[FilingEvent]) -> str:
    manifest = [
        {
            "ticker": event.ticker.upper(),
            "accession_number": event.accession_number,
            "feature_value": format(float(event.feature_value), ".17g"),
        }
        for event in sorted(
            events,
            key=lambda item: (item.ticker.upper(), item.accession_number),
        )
        if event.feature_value is not None
    ]
    return _stable_digest(manifest)


def _universe_snapshot_id(events: list[FilingEvent]) -> str:
    manifest = [
        {
            "ticker": event.ticker.upper(),
            "accession_number": event.accession_number,
            "available_at": event.available_at.isoformat(),
            "max_source_available_at": event.max_source_available_at.isoformat(),
        }
        for event in sorted(events, key=lambda item: (item.ticker.upper(), item.accession_number))
    ]
    return _stable_digest(manifest)


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
