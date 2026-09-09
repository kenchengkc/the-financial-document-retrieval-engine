"""Sealed walk-forward evaluation for point-in-time filing signals.

This module owns research isolation, not signal diagnostics. A signal definition
is frozen before the study runs. The engine then constructs rolling or expanding
train -> validation -> test folds, purges development observations whose forward
outcomes would not yet have been fully observable at the test boundary, and
admits only eligible test-fold observations to the aggregate OOS sample.

ICIR, quantile monotonicity, turnover, costs, and promotion/rejection belong in
layers above this one. Keeping those concerns separate makes it harder to tune
on the same outcomes later presented as out-of-sample evidence.
"""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import (
    EventReturn,
    EventStudyConfig,
    FilingEvent,
    MarketBar,
    run_event_study,
    validate_event_inputs,
)

WalkForwardMode = Literal["rolling", "expanding"]
FoldStatus = Literal["eligible", "insufficient_data"]


class WalkForwardConfig(BaseModel):
    """Calendar schedule and minimum breadth for a sealed walk-forward study.

    Intervals are half-open: ``[start, end)``. ``step_months`` must be at least
    ``test_months`` so one accession cannot appear in multiple OOS test folds.
    """

    mode: WalkForwardMode = "expanding"
    train_months: int = Field(default=36, ge=1)
    validation_months: int = Field(default=12, ge=1)
    test_months: int = Field(default=12, ge=1)
    step_months: int = Field(default=12, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    purge_unrealized_development: bool = True
    min_train_events: int = Field(default=1, ge=1)
    min_validation_events: int = Field(default=1, ge=1)
    min_test_events: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_schedule(self) -> WalkForwardConfig:
        if self.step_months < self.test_months:
            raise ValueError(
                "step_months must be >= test_months so OOS test folds do not overlap"
            )
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class WalkForwardFoldDefinition(BaseModel):
    fold_number: int = Field(ge=1)
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date


class WalkForwardObservation(BaseModel):
    """Feature/outcome pair plus the date the full forward outcome was known."""

    ticker: str
    accession_number: str
    event_session: date
    window: str
    window_end_session: date
    feature_value: float
    outcome_value: float
    available_at: datetime
    max_source_available_at: datetime
    feature_lineage_id: str | None = None


class WalkForwardOOSObservation(WalkForwardObservation):
    fold_id: str


class WalkForwardFoldResult(BaseModel):
    fold_id: str
    definition: WalkForwardFoldDefinition
    development_cutoff: date
    status: FoldStatus
    eligibility_reasons: list[str] = Field(default_factory=list)
    train_accessions: list[str]
    validation_accessions: list[str]
    purged_development_accessions: list[str]
    test_accessions: list[str]
    test_observation_count: int


class WalkForwardStudyReport(BaseModel):
    experiment_key: str
    signal_name: str
    outcome_name: str = "abnormal_return"
    selection_policy: str = "precommitted_signal_definition"
    sealed_oos: bool = True
    dataset_version: str
    feature_version: str
    market_data_version: str
    universe_snapshot_id: str
    feature_snapshot_id: str
    code_sha: str
    definition: dict[str, object] = Field(default_factory=dict)
    feature_lineage_digest: str | None = None
    feature_lineage_complete: bool = False
    event_study_config: EventStudyConfig
    walk_forward_config: WalkForwardConfig
    fold_count: int
    eligible_fold_count: int
    oos_event_count: int
    oos_observation_count: int
    folds: list[WalkForwardFoldResult]
    oos_observations: list[WalkForwardOOSObservation]


def generate_walk_forward_schedule(
    config: WalkForwardConfig,
    event_sessions: list[date],
) -> list[WalkForwardFoldDefinition]:
    """Generate deterministic complete test folds over the observed sample span."""
    if not event_sessions:
        raise ValueError("walk-forward study requires at least one observed event session")

    minimum = min(event_sessions)
    maximum = max(event_sessions)
    study_start = config.start_date or date(minimum.year, 1, 1)
    study_end = config.end_date or date(maximum.year + 1, 1, 1)
    if study_end <= study_start:
        raise ValueError("walk-forward study end must be after its start")

    folds: list[WalkForwardFoldDefinition] = []
    offset = 0
    while True:
        if config.mode == "rolling":
            train_start = _add_months(study_start, offset)
            train_end = _add_months(train_start, config.train_months)
        else:
            train_start = study_start
            train_end = _add_months(study_start, config.train_months + offset)
        validation_start = train_end
        validation_end = _add_months(validation_start, config.validation_months)
        test_start = validation_end
        test_end = _add_months(test_start, config.test_months)
        if test_end > study_end:
            break
        folds.append(
            WalkForwardFoldDefinition(
                fold_number=len(folds) + 1,
                train_start=train_start,
                train_end=train_end,
                validation_start=validation_start,
                validation_end=validation_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        offset += config.step_months

    if not folds:
        raise ValueError("study span is too short for one complete walk-forward fold")
    return folds


def build_walk_forward_folds(
    observations: list[WalkForwardObservation],
    config: WalkForwardConfig,
) -> tuple[list[WalkForwardFoldResult], list[WalkForwardOOSObservation]]:
    """Partition observations and construct the sealed aggregate OOS sample.

    A development accession is purged when any requested forward window ends on
    or after the test start. A researcher standing immediately before the test
    interval therefore cannot use an outcome that has not completely happened.
    Ineligible folds remain in the audit trail but contribute no OOS outcomes.
    """
    if not observations:
        raise ValueError("walk-forward study requires at least one feature/outcome observation")

    by_accession: dict[str, list[WalkForwardObservation]] = defaultdict(list)
    event_session_by_accession: dict[str, date] = {}
    for observation in observations:
        existing = event_session_by_accession.setdefault(
            observation.accession_number, observation.event_session
        )
        if existing != observation.event_session:
            raise ValueError(
                f"Inconsistent event session for {observation.accession_number}"
            )
        by_accession[observation.accession_number].append(observation)

    schedule = generate_walk_forward_schedule(
        config,
        list(event_session_by_accession.values()),
    )
    folds: list[WalkForwardFoldResult] = []
    oos: list[WalkForwardOOSObservation] = []
    seen_oos_accessions: set[str] = set()

    for definition in schedule:
        train_candidates = _accessions_in_interval(
            event_session_by_accession,
            definition.train_start,
            definition.train_end,
        )
        validation_candidates = _accessions_in_interval(
            event_session_by_accession,
            definition.validation_start,
            definition.validation_end,
        )
        test_accessions = _accessions_in_interval(
            event_session_by_accession,
            definition.test_start,
            definition.test_end,
        )

        purged: set[str] = set()
        if config.purge_unrealized_development:
            for accession in [*train_candidates, *validation_candidates]:
                if any(
                    item.window_end_session >= definition.test_start
                    for item in by_accession[accession]
                ):
                    purged.add(accession)
        train_accessions = [item for item in train_candidates if item not in purged]
        validation_accessions = [
            item for item in validation_candidates if item not in purged
        ]
        _validate_partition(train_accessions, validation_accessions, test_accessions)

        reasons: list[str] = []
        if len(train_accessions) < config.min_train_events:
            reasons.append(
                f"train events {len(train_accessions)} < minimum {config.min_train_events}"
            )
        if len(validation_accessions) < config.min_validation_events:
            reasons.append(
                "validation events "
                f"{len(validation_accessions)} < minimum {config.min_validation_events}"
            )
        if len(test_accessions) < config.min_test_events:
            reasons.append(
                f"test events {len(test_accessions)} < minimum {config.min_test_events}"
            )
        status: FoldStatus = "insufficient_data" if reasons else "eligible"

        fold_manifest = {
            "definition": definition.model_dump(mode="json"),
            "train_accessions": train_accessions,
            "validation_accessions": validation_accessions,
            "purged_development_accessions": sorted(purged),
            "test_accessions": test_accessions,
        }
        fold_id = _stable_digest(fold_manifest)

        test_observation_count = 0
        if status == "eligible":
            overlap = seen_oos_accessions.intersection(test_accessions)
            if overlap:
                raise ValueError(
                    "OOS accession appears in multiple test folds: "
                    + ", ".join(sorted(overlap))
                )
            seen_oos_accessions.update(test_accessions)
            for accession in test_accessions:
                for observation in by_accession[accession]:
                    oos.append(
                        WalkForwardOOSObservation(
                            **observation.model_dump(),
                            fold_id=fold_id,
                        )
                    )
                    test_observation_count += 1

        folds.append(
            WalkForwardFoldResult(
                fold_id=fold_id,
                definition=definition,
                development_cutoff=definition.test_start,
                status=status,
                eligibility_reasons=reasons,
                train_accessions=train_accessions,
                validation_accessions=validation_accessions,
                purged_development_accessions=sorted(purged),
                test_accessions=test_accessions,
                test_observation_count=test_observation_count,
            )
        )

    oos.sort(key=lambda item: (item.event_session, item.accession_number, item.window))
    return folds, oos


def run_walk_forward_signal_study(
    events: list[FilingEvent],
    bars: list[MarketBar],
    event_study_config: EventStudyConfig,
    walk_forward_config: WalkForwardConfig,
    *,
    signal_name: str,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    definition: dict[str, object] | None = None,
) -> WalkForwardStudyReport:
    """Create a reproducible sealed-OOS report for a precommitted signal."""
    scored = [event for event in events if event.feature_value is not None]
    if not scored:
        raise ValueError("walk-forward signal study requires scored filing events")
    validate_event_inputs(scored)

    # This framework owns split semantics. Disable the legacy split-date summary
    # in the underlying event-study engine so there is only one OOS definition.
    base_config = event_study_config.model_copy(update={"walk_forward_splits": []})
    base = run_event_study(
        scored,
        bars,
        base_config,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
    )
    observations = _walk_forward_observations(scored, bars, base.observations, base_config)
    folds, oos = build_walk_forward_folds(observations, walk_forward_config)

    lineage_digest, lineage_complete = _feature_lineage_digest(scored)
    market_version = market_data_version(bars)
    universe_snapshot_id = _universe_snapshot_id(scored)
    feature_snapshot_id = _feature_snapshot_id(scored)
    precommitted_definition = definition or {}
    manifest = {
        "signal_name": signal_name,
        "outcome_name": "abnormal_return",
        "selection_policy": "precommitted_signal_definition",
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "market_data_version": market_version,
        "universe_snapshot_id": universe_snapshot_id,
        "feature_snapshot_id": feature_snapshot_id,
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
        market_data_version=market_version,
        universe_snapshot_id=universe_snapshot_id,
        feature_snapshot_id=feature_snapshot_id,
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


def persist_walk_forward_study(
    session: Session,
    report: WalkForwardStudyReport,
) -> ResearchExperiment:
    """Persist idempotently in the existing generic experiment store."""
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.experiment_key
        )
    )
    config_json = {
        "signal_name": report.signal_name,
        "definition": report.definition,
        "event_study": report.event_study_config.model_dump(mode="json"),
        "walk_forward": report.walk_forward_config.model_dump(mode="json"),
    }
    payload = report.model_dump(mode="json")
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.experiment_key,
            experiment_type="walk_forward_signal_study",
            dataset_version=report.dataset_version,
            feature_version=report.feature_version,
            code_sha=report.code_sha,
            config_json=config_json,
            results_json=payload,
        )
        session.add(experiment)
    else:
        experiment.config_json = config_json
        experiment.results_json = payload
    session.commit()
    session.refresh(experiment)
    return experiment


def write_walk_forward_report(
    path: str | Path,
    report: WalkForwardStudyReport,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def market_data_version(bars: list[MarketBar]) -> str:
    """Full deterministic SHA-256 of the market-data input snapshot."""
    digest = hashlib.sha256()
    for bar in sorted(
        bars,
        key=lambda item: (item.ticker.upper(), item.date, item.adjusted_close),
    ):
        digest.update(
            (
                f"{bar.ticker.upper()}|{bar.date.isoformat()}|"
                f"{format(bar.adjusted_close, '.17g')}\n"
            ).encode()
        )
    return digest.hexdigest()


def _walk_forward_observations(
    events: list[FilingEvent],
    bars: list[MarketBar],
    returns: list[EventReturn],
    config: EventStudyConfig,
) -> list[WalkForwardObservation]:
    events_by_accession = {event.accession_number: event for event in events}
    bars_by_ticker: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_ticker[bar.ticker.upper()].append(bar)
    for ticker_bars in bars_by_ticker.values():
        ticker_bars.sort(key=lambda item: item.date)
    end_offset_by_window = {window.label: window.end for window in config.windows}

    observations: list[WalkForwardObservation] = []
    for outcome in returns:
        event = events_by_accession.get(outcome.accession_number)
        if event is None or event.feature_value is None:
            continue
        ticker_bars = bars_by_ticker.get(outcome.ticker.upper(), [])
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
    """Fingerprint realized signal values separately from universe membership."""
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
    """Fingerprint event membership and PIT availability, not signal values."""
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


def _accessions_in_interval(
    sessions: dict[str, date],
    start: date,
    end: date,
) -> list[str]:
    return [
        accession
        for accession, event_session in sorted(
            sessions.items(), key=lambda item: (item[1], item[0])
        )
        if start <= event_session < end
    ]


def _validate_partition(
    train_accessions: list[str],
    validation_accessions: list[str],
    test_accessions: list[str],
) -> None:
    train = set(train_accessions)
    validation = set(validation_accessions)
    test = set(test_accessions)
    if train & validation or train & test or validation & test:
        raise ValueError("walk-forward train, validation, and test partitions overlap")


def _stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)
