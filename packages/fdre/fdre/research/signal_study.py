"""Cross-sectional signal study on top of the event-study engine.

Splits filing events by a point-in-time feature (e.g. disclosure similarity)
into quantile portfolios, then measures forward benchmark-adjusted returns,
the information coefficient, and a long-short spread with bootstrap
significance. This is the layer that turns a single PIT feature into a
testable, no-lookahead trading signal (cf. Cohen, Malloy & Nguyen, "Lazy
Prices", 2020).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from math import sqrt
from statistics import mean

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import (
    EventStudyConfig,
    FilingEvent,
    MarketBar,
    _event_session_index,
    run_event_study,
    validate_event_inputs,
)


class QuantileResult(BaseModel):
    quantile: int
    sample_size: int
    mean_abnormal_return: float | None


class SignalWindowResult(BaseModel):
    window: str
    sample_size: int
    information_coefficient: float | None
    ic_t_stat: float | None
    quantiles: list[QuantileResult]
    long_short_mean: float | None
    long_short_ci_low: float | None
    long_short_ci_high: float | None
    long_short_p_value: float | None


class SignalStudyReport(BaseModel):
    experiment_key: str
    signal_name: str
    n_quantiles: int
    dataset_version: str
    feature_version: str
    code_sha: str
    outcome_name: str = "abnormal_return"
    config: EventStudyConfig
    event_count: int
    results: list[SignalWindowResult]


def run_signal_study(
    events: list[FilingEvent],
    bars: list[MarketBar],
    config: EventStudyConfig,
    *,
    signal_name: str,
    n_quantiles: int,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    outcome_name: str = "abnormal_return",
) -> SignalStudyReport:
    scored = [event for event in events if event.feature_value is not None]
    base = run_event_study(
        scored,
        bars,
        config,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
    )
    feature_by_accession = {event.accession_number: event.feature_value for event in scored}

    by_window: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for observation in base.observations:
        feature = feature_by_accession.get(observation.accession_number)
        if feature is not None:
            by_window[observation.window].append((feature, observation.abnormal_return))

    return _build_signal_report(
        scored,
        by_window,
        config,
        signal_name=signal_name,
        outcome_name=outcome_name,
        n_quantiles=n_quantiles,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
        event_count=base.event_count,
    )


def run_realized_volatility_signal_study(
    events: list[FilingEvent],
    bars: list[MarketBar],
    config: EventStudyConfig,
    *,
    signal_name: str,
    n_quantiles: int,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
) -> SignalStudyReport:
    scored = [event for event in events if event.feature_value is not None]
    validate_event_inputs(scored)
    bars_by_ticker: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_ticker[bar.ticker.upper()].append(bar)
    for ticker_bars in bars_by_ticker.values():
        ticker_bars.sort(key=lambda bar: bar.date)

    by_window: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for event in scored:
        feature = event.feature_value
        if feature is None:
            continue
        ticker_bars = bars_by_ticker.get(event.ticker.upper(), [])
        event_index = _event_session_index(event.available_at, ticker_bars, config)
        if event_index is None:
            continue
        for window in config.windows:
            start_index = event_index + window.start
            end_index = event_index + window.end
            if start_index < 0 or end_index >= len(ticker_bars):
                continue
            daily_returns = [
                ticker_bars[index].adjusted_close / ticker_bars[index - 1].adjusted_close
                - 1
                for index in range(start_index + 1, end_index + 1)
            ]
            if not daily_returns:
                continue
            realized_volatility = sqrt(mean(value * value for value in daily_returns))
            by_window[window.label].append((feature, realized_volatility))

    return _build_signal_report(
        scored,
        by_window,
        config,
        signal_name=signal_name,
        outcome_name="realized_volatility",
        n_quantiles=n_quantiles,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
        event_count=len(scored),
    )


def _build_signal_report(
    scored: list[FilingEvent],
    by_window: dict[str, list[tuple[float, float]]],
    config: EventStudyConfig,
    *,
    signal_name: str,
    outcome_name: str,
    n_quantiles: int,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    event_count: int,
) -> SignalStudyReport:
    feature_by_accession = {event.accession_number: event.feature_value for event in scored}
    rng = random.Random(config.random_seed)
    results = [
        _summarize_window(
            window.label,
            by_window.get(window.label, []),
            n_quantiles,
            config,
            rng,
        )
        for window in config.windows
    ]

    manifest = {
        "signal_name": signal_name,
        "outcome_name": outcome_name,
        "n_quantiles": n_quantiles,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "code_sha": code_sha,
        "config": config.model_dump(mode="json"),
        "events": sorted(feature_by_accession),
    }
    experiment_key = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return SignalStudyReport(
        experiment_key=experiment_key,
        signal_name=signal_name,
        outcome_name=outcome_name,
        n_quantiles=n_quantiles,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
        config=config,
        event_count=event_count,
        results=results,
    )


def persist_signal_study(session: Session, report: SignalStudyReport) -> ResearchExperiment:
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.experiment_key
        )
    )
    payload = report.model_dump(mode="json")
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.experiment_key,
            experiment_type="signal_study",
            dataset_version=report.dataset_version,
            feature_version=report.feature_version,
            code_sha=report.code_sha,
            config_json=report.config.model_dump(mode="json"),
            results_json=payload,
        )
        session.add(experiment)
    else:
        experiment.config_json = report.config.model_dump(mode="json")
        experiment.results_json = payload
    session.commit()
    session.refresh(experiment)
    return experiment


def _summarize_window(
    window: str,
    pairs: list[tuple[float, float]],
    n_quantiles: int,
    config: EventStudyConfig,
    rng: random.Random,
) -> SignalWindowResult:
    if len(pairs) < n_quantiles * 2:
        return SignalWindowResult(
            window=window,
            sample_size=len(pairs),
            information_coefficient=None,
            ic_t_stat=None,
            quantiles=[],
            long_short_mean=None,
            long_short_ci_low=None,
            long_short_ci_high=None,
            long_short_p_value=None,
        )
    features = [feature for feature, _ in pairs]
    returns = [value for _, value in pairs]
    ic = _spearman(features, returns)
    ic_t = (
        ic * ((len(pairs) - 2) / (1 - ic * ic)) ** 0.5
        if ic is not None and abs(ic) < 1.0
        else None
    )

    ordered = sorted(pairs, key=lambda item: item[0])
    buckets = _split_quantiles(ordered, n_quantiles)
    quantiles = [
        QuantileResult(
            quantile=index + 1,
            sample_size=len(bucket),
            mean_abnormal_return=mean(value for _, value in bucket) if bucket else None,
        )
        for index, bucket in enumerate(buckets)
    ]
    low_returns = [value for _, value in buckets[0]]
    high_returns = [value for _, value in buckets[-1]]
    spread = mean(high_returns) - mean(low_returns)
    ci_low, ci_high, p_value = _bootstrap_difference(high_returns, low_returns, config, rng)
    return SignalWindowResult(
        window=window,
        sample_size=len(pairs),
        information_coefficient=ic,
        ic_t_stat=ic_t,
        quantiles=quantiles,
        long_short_mean=spread,
        long_short_ci_low=ci_low,
        long_short_ci_high=ci_high,
        long_short_p_value=p_value,
    )


def _split_quantiles(
    ordered: list[tuple[float, float]],
    n_quantiles: int,
) -> list[list[tuple[float, float]]]:
    size = len(ordered)
    buckets: list[list[tuple[float, float]]] = []
    for index in range(n_quantiles):
        start = index * size // n_quantiles
        end = (index + 1) * size // n_quantiles
        buckets.append(ordered[start:end])
    return buckets


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3:
        return None
    left_ranks = _rank(left)
    right_ranks = _rank(right)
    return _pearson(left_ranks, right_ranks)


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average_rank = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[order[position]] = average_rank
        index = end + 1
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    n = len(left)
    if n == 0:
        return None
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    numerator = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=False)
    )
    var_left = sum((a - mean_left) ** 2 for a in left)
    var_right = sum((b - mean_right) ** 2 for b in right)
    if var_left == 0 or var_right == 0:
        return None
    return float(numerator / (var_left * var_right) ** 0.5)


def _bootstrap_difference(
    high: list[float],
    low: list[float],
    config: EventStudyConfig,
    rng: random.Random,
) -> tuple[float | None, float | None, float | None]:
    if not high or not low:
        return None, None, None
    samples = sorted(
        mean(rng.choices(high, k=len(high))) - mean(rng.choices(low, k=len(low)))
        for _ in range(config.bootstrap_iterations)
    )
    alpha = 1 - config.confidence_level
    low_ci = samples[max(0, round((len(samples) - 1) * (alpha / 2)))]
    high_ci = samples[min(len(samples) - 1, round((len(samples) - 1) * (1 - alpha / 2)))]
    below = sum(sample <= 0 for sample in samples) / len(samples)
    above = sum(sample >= 0 for sample in samples) / len(samples)
    return low_ci, high_ci, min(1.0, 2 * min(below, above))
