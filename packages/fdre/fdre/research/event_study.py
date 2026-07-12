from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment


class MarketBar(BaseModel):
    ticker: str
    date: date
    adjusted_close: float = Field(gt=0)


class FilingEvent(BaseModel):
    ticker: str
    accession_number: str
    available_at: datetime
    max_source_available_at: datetime
    feature_value: float | None = None


class EventWindow(BaseModel):
    start: int
    end: int

    @model_validator(mode="after")
    def validate_window(self) -> EventWindow:
        if self.end <= self.start:
            raise ValueError("event window end must be greater than start")
        return self

    @property
    def label(self) -> str:
        return f"{self.start}:{self.end}"


class EventStudyConfig(BaseModel):
    benchmark_ticker: str = "SPY"
    windows: list[EventWindow] = Field(
        default_factory=lambda: [
            EventWindow(start=0, end=1),
            EventWindow(start=-1, end=1),
            EventWindow(start=0, end=5),
        ]
    )
    bootstrap_iterations: int = Field(default=1000, ge=100, le=100_000)
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1.0)
    random_seed: int = 17
    market_timezone: str = "America/New_York"
    market_close: time = time(16, 0)
    walk_forward_splits: list[date] = Field(default_factory=list)


class EventReturn(BaseModel):
    ticker: str
    accession_number: str
    event_session: date
    window: str
    asset_return: float
    benchmark_return: float
    abnormal_return: float


class EventWindowResult(BaseModel):
    window: str
    sample_size: int
    mean_abnormal_return: float | None
    median_abnormal_return: float | None
    confidence_interval_low: float | None
    confidence_interval_high: float | None
    bootstrap_p_value: float | None
    adjusted_p_value: float | None


class WalkForwardResult(BaseModel):
    split_date: date
    train_event_count: int
    test_event_count: int
    test_mean_abnormal_return: dict[str, float | None]


class EventStudyReport(BaseModel):
    experiment_key: str
    dataset_version: str
    feature_version: str
    code_sha: str
    config: EventStudyConfig
    event_count: int
    results: list[EventWindowResult]
    walk_forward: list[WalkForwardResult]
    observations: list[EventReturn]


def load_market_bars(path: str | Path) -> list[MarketBar]:
    source = Path(path)
    if source.suffix.casefold() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as error:
            raise RuntimeError(
                "Parquet market data requires `pip install -e '.[data]'`."
            ) from error
        rows = pq.read_table(source).to_pylist()  # type: ignore[no-untyped-call, unused-ignore]
    else:
        with source.open(newline="", encoding="utf-8") as input_file:
            rows = list(csv.DictReader(input_file))
    return [
        MarketBar(
            ticker=str(row["ticker"]).upper(),
            date=_parse_date(row["date"]),
            adjusted_close=float(row["adjusted_close"]),
        )
        for row in rows
    ]


def load_filing_events(
    path: str | Path,
    *,
    feature: str | None = None,
) -> tuple[list[FilingEvent], str, str]:
    source = Path(path)
    if source.suffix.casefold() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as error:
            raise RuntimeError(
                "Parquet panel input requires `pip install -e '.[data]'`."
            ) from error
        rows = pq.read_table(source).to_pylist()  # type: ignore[no-untyped-call, unused-ignore]
    elif source.suffix.casefold() == ".csv":
        with source.open(newline="", encoding="utf-8") as input_file:
            rows = list(csv.DictReader(input_file))
    else:
        payload = json.loads(source.read_text())
        if not isinstance(payload, list):
            raise ValueError("Research panel JSON must be an array of row objects")
        rows = payload
    events = [
        FilingEvent(
            ticker=str(row["ticker"]).upper(),
            accession_number=str(row["accession_number"]),
            available_at=_parse_datetime(row["available_at"]),
            max_source_available_at=_parse_datetime(row["max_source_available_at"]),
            feature_value=(
                float(row[feature])
                if feature and row.get(feature) not in {None, ""}
                else None
            ),
        )
        for row in rows
    ]
    dataset_version = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    feature_version = (
        str(rows[0].get("calculation_version", "unknown")) if rows else "unknown"
    )
    return events, dataset_version, feature_version


def run_event_study(
    events: list[FilingEvent],
    bars: list[MarketBar],
    config: EventStudyConfig,
    *,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
) -> EventStudyReport:
    validate_event_inputs(events)
    bars_by_ticker: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_ticker[bar.ticker.upper()].append(bar)
    for ticker_bars in bars_by_ticker.values():
        ticker_bars.sort(key=lambda bar: bar.date)

    observations: list[EventReturn] = []
    event_sessions: dict[str, date] = {}
    for event in events:
        ticker_bars = bars_by_ticker.get(event.ticker.upper(), [])
        benchmark_bars = bars_by_ticker.get(config.benchmark_ticker.upper(), [])
        event_index = _event_session_index(event.available_at, ticker_bars, config)
        if event_index is None:
            continue
        event_session = ticker_bars[event_index].date
        event_sessions[event.accession_number] = event_session
        benchmark_by_date = {bar.date: bar for bar in benchmark_bars}
        for window in config.windows:
            start_index = event_index + window.start
            end_index = event_index + window.end
            if start_index < 0 or end_index >= len(ticker_bars):
                continue
            start_bar = ticker_bars[start_index]
            end_bar = ticker_bars[end_index]
            benchmark_start = benchmark_by_date.get(start_bar.date)
            benchmark_end = benchmark_by_date.get(end_bar.date)
            if benchmark_start is None or benchmark_end is None:
                continue
            asset_return = end_bar.adjusted_close / start_bar.adjusted_close - 1
            benchmark_return = (
                benchmark_end.adjusted_close / benchmark_start.adjusted_close - 1
            )
            observations.append(
                EventReturn(
                    ticker=event.ticker,
                    accession_number=event.accession_number,
                    event_session=event_session,
                    window=window.label,
                    asset_return=asset_return,
                    benchmark_return=benchmark_return,
                    abnormal_return=asset_return - benchmark_return,
                )
            )

    results = _summarize_windows(observations, config)
    walk_forward = _walk_forward_results(
        events,
        event_sessions,
        observations,
        config.walk_forward_splits,
    )
    manifest = {
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "code_sha": code_sha,
        "config": config.model_dump(mode="json"),
        "events": [
            {
                "ticker": event.ticker,
                "accession": event.accession_number,
                "available_at": event.available_at.isoformat(),
            }
            for event in events
        ],
    }
    experiment_key = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return EventStudyReport(
        experiment_key=experiment_key,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
        config=config,
        event_count=len(event_sessions),
        results=results,
        walk_forward=walk_forward,
        observations=observations,
    )


def persist_event_study(session: Session, report: EventStudyReport) -> ResearchExperiment:
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.experiment_key
        )
    )
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.experiment_key,
            experiment_type="event_study",
            dataset_version=report.dataset_version,
            feature_version=report.feature_version,
            code_sha=report.code_sha,
            config_json=report.config.model_dump(mode="json"),
            results_json=report.model_dump(mode="json"),
        )
        session.add(experiment)
    else:
        experiment.config_json = report.config.model_dump(mode="json")
        experiment.results_json = report.model_dump(mode="json")
    session.commit()
    session.refresh(experiment)
    return experiment


def write_event_study_report(
    path: str | Path,
    report: EventStudyReport,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def validate_event_inputs(events: list[FilingEvent]) -> None:
    for event in events:
        if event.max_source_available_at > event.available_at:
            raise ValueError(
                f"Feature leakage for {event.accession_number}: source timestamp "
                "is after event availability"
            )


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
    return next(
        (index for index, bar in enumerate(bars) if bar.date >= target_date),
        None,
    )


def _summarize_windows(
    observations: list[EventReturn],
    config: EventStudyConfig,
) -> list[EventWindowResult]:
    by_window: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        by_window[observation.window].append(observation.abnormal_return)
    results: list[EventWindowResult] = []
    for window in config.windows:
        values = by_window.get(window.label, [])
        if not values:
            results.append(
                EventWindowResult(
                    window=window.label,
                    sample_size=0,
                    mean_abnormal_return=None,
                    median_abnormal_return=None,
                    confidence_interval_low=None,
                    confidence_interval_high=None,
                    bootstrap_p_value=None,
                    adjusted_p_value=None,
                )
            )
            continue
        low, high, p_value = _bootstrap_mean(values, config)
        results.append(
            EventWindowResult(
                window=window.label,
                sample_size=len(values),
                mean_abnormal_return=mean(values),
                median_abnormal_return=median(values),
                confidence_interval_low=low,
                confidence_interval_high=high,
                bootstrap_p_value=p_value,
                adjusted_p_value=None,
            )
        )
    _apply_benjamini_hochberg(results)
    return results


def _bootstrap_mean(
    values: list[float],
    config: EventStudyConfig,
) -> tuple[float, float, float]:
    rng = random.Random(config.random_seed + len(values))
    samples = sorted(
        mean(rng.choices(values, k=len(values)))
        for _ in range(config.bootstrap_iterations)
    )
    alpha = 1 - config.confidence_level
    low = _quantile(samples, alpha / 2)
    high = _quantile(samples, 1 - alpha / 2)
    below = sum(sample <= 0 for sample in samples) / len(samples)
    above = sum(sample >= 0 for sample in samples) / len(samples)
    return low, high, min(1.0, 2 * min(below, above))


def _apply_benjamini_hochberg(results: list[EventWindowResult]) -> None:
    tested = [
        (index, result.bootstrap_p_value)
        for index, result in enumerate(results)
        if result.bootstrap_p_value is not None
    ]
    ordered = sorted(tested, key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running = 1.0
    for rank, (index, p_value) in reversed(list(enumerate(ordered, start=1))):
        running = min(running, p_value * len(ordered) / rank)
        adjusted[index] = min(1.0, running)
    for index, value in adjusted.items():
        results[index].adjusted_p_value = value


def _walk_forward_results(
    events: list[FilingEvent],
    event_sessions: dict[str, date],
    observations: list[EventReturn],
    splits: list[date],
) -> list[WalkForwardResult]:
    by_accession: dict[str, list[EventReturn]] = defaultdict(list)
    for observation in observations:
        by_accession[observation.accession_number].append(observation)
    results: list[WalkForwardResult] = []
    for split in splits:
        train = [
            event
            for event in events
            if event.accession_number in event_sessions
            and event_sessions[event.accession_number] < split
        ]
        test = [
            event
            for event in events
            if event.accession_number in event_sessions
            and event_sessions[event.accession_number] >= split
        ]
        test_means: dict[str, float | None] = {}
        for window in {
            observation.window
            for event in test
            for observation in by_accession.get(event.accession_number, [])
        }:
            values = [
                observation.abnormal_return
                for event in test
                for observation in by_accession.get(event.accession_number, [])
                if observation.window == window
            ]
            test_means[window] = mean(values) if values else None
        results.append(
            WalkForwardResult(
                split_date=split,
                train_event_count=len(train),
                test_event_count=len(test),
                test_mean_abnormal_return=test_means,
            )
        )
    return results


def _quantile(values: list[float], quantile: float) -> float:
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return values[index]


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
