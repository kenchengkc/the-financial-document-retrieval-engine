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

from pydantic import BaseModel, Field
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
    cluster_count: int | None = None
    information_coefficient: float | None
    ic_t_stat: float | None
    quantiles: list[QuantileResult]
    long_short_mean: float | None
    long_short_ci_low: float | None
    long_short_ci_high: float | None
    long_short_p_value: float | None
    long_short_adjusted_p_value: float | None = None


class SignalPeriodResult(BaseModel):
    period: str
    window: str
    sample_size: int
    information_coefficient: float | None
    long_short_mean: float | None


class SignalConstituent(BaseModel):
    ticker: str
    name: str
    value: float
    side: str  # "long" (top quintile) | "short" (bottom quintile)


class SignalStudyReport(BaseModel):
    experiment_key: str
    signal_name: str
    n_quantiles: int
    dataset_version: str
    feature_version: str
    code_sha: str
    outcome_name: str = "abnormal_return"
    bootstrap_unit: str = "issuer"
    neutralization: str = "none"
    definition: dict[str, object] = Field(default_factory=dict)
    config: EventStudyConfig
    event_count: int
    results: list[SignalWindowResult]
    period_results: list[SignalPeriodResult] = Field(default_factory=list)
    constituents: list[SignalConstituent] = Field(default_factory=list)


SignalPair = tuple[float, float, str]


def _winsorize_outcomes(
    by_window: dict[str, list[SignalPair]], pct: float
) -> dict[str, list[SignalPair]]:
    """Clip each window's forward outcomes to its [pct, 1-pct] empirical quantiles.

    Small samples with a few highly volatile constituents let single names dominate
    a quantile's mean; winsorizing the return distribution (standard in factor
    research) limits that outlier influence without dropping observations.
    """
    clipped: dict[str, list[SignalPair]] = {}
    for label, pairs in by_window.items():
        clipped[label] = _winsorize_pairs(pairs, pct)
    return clipped


def _winsorize_pairs(
    pairs: list[SignalPair], pct: float
) -> list[SignalPair]:
    if len(pairs) < 5:
        return pairs
    outcomes = sorted(outcome for _, outcome, _ in pairs)
    last = len(outcomes) - 1
    low = outcomes[int(pct * last)]
    high = outcomes[int((1 - pct) * last)]
    return [
        (feature, min(max(outcome, low), high), cluster)
        for feature, outcome, cluster in pairs
    ]


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
    winsorize_pct: float | None = None,
    neutralization: str = "none",
    definition: dict[str, object] | None = None,
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
    ticker_by_accession = {event.accession_number: event.ticker for event in scored}

    by_window: dict[str, list[SignalPair]] = defaultdict(list)
    by_period: dict[tuple[str, str], list[SignalPair]] = defaultdict(list)
    for observation in base.observations:
        feature = feature_by_accession.get(observation.accession_number)
        if feature is not None:
            pair = (
                feature,
                observation.abnormal_return,
                ticker_by_accession[observation.accession_number],
            )
            by_window[observation.window].append(pair)
            by_period[(str(observation.event_session.year), observation.window)].append(
                pair
            )

    if winsorize_pct:
        by_window = defaultdict(list, _winsorize_outcomes(by_window, winsorize_pct))
        by_period = defaultdict(
            list,
            {
                key: _winsorize_pairs(pairs, winsorize_pct)
                for key, pairs in by_period.items()
            },
        )

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
        neutralization=neutralization,
        definition=definition or {},
        by_period=by_period,
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
    neutralization: str = "none",
    definition: dict[str, object] | None = None,
) -> SignalStudyReport:
    scored = [event for event in events if event.feature_value is not None]
    validate_event_inputs(scored)
    bars_by_ticker: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_ticker[bar.ticker.upper()].append(bar)
    for ticker_bars in bars_by_ticker.values():
        ticker_bars.sort(key=lambda bar: bar.date)

    by_window: dict[str, list[SignalPair]] = defaultdict(list)
    by_period: dict[tuple[str, str], list[SignalPair]] = defaultdict(list)
    observed_accessions: set[str] = set()
    for event in scored:
        feature = event.feature_value
        if feature is None:
            continue
        ticker_bars = bars_by_ticker.get(event.ticker.upper(), [])
        event_index = _event_session_index(event.available_at, ticker_bars, config)
        if event_index is None:
            continue
        event_period = str(ticker_bars[event_index].date.year)
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
            pair = (feature, realized_volatility, event.ticker)
            by_window[window.label].append(pair)
            by_period[(event_period, window.label)].append(pair)
            observed_accessions.add(event.accession_number)

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
        event_count=len(observed_accessions),
        neutralization=neutralization,
        definition=definition or {},
        by_period=by_period,
    )


def _build_signal_report(
    scored: list[FilingEvent],
    by_window: dict[str, list[SignalPair]],
    config: EventStudyConfig,
    *,
    signal_name: str,
    outcome_name: str,
    n_quantiles: int,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
    event_count: int,
    neutralization: str,
    definition: dict[str, object],
    by_period: dict[tuple[str, str], list[SignalPair]],
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
    _apply_benjamini_hochberg(results)

    manifest = {
        "signal_name": signal_name,
        "outcome_name": outcome_name,
        "bootstrap_unit": "issuer",
        "n_quantiles": n_quantiles,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "code_sha": code_sha,
        "neutralization": neutralization,
        "definition": definition,
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
        neutralization=neutralization,
        definition=definition,
        config=config,
        event_count=event_count,
        results=results,
        period_results=_period_results(by_period, n_quantiles),
    )


def _period_results(
    grouped: dict[tuple[str, str], list[SignalPair]],
    n_quantiles: int,
) -> list[SignalPeriodResult]:
    results: list[SignalPeriodResult] = []
    for (period, window), pairs in sorted(grouped.items()):
        information_coefficient = (
            _spearman(
                [feature for feature, _, _ in pairs],
                [outcome for _, outcome, _ in pairs],
            )
            if len(pairs) >= 3
            else None
        )
        long_short_mean: float | None = None
        if len(pairs) >= n_quantiles * 2:
            buckets = _split_quantiles(
                sorted(pairs, key=lambda item: item[0]),
                n_quantiles,
            )
            long_short_mean = mean(value for _, value, _ in buckets[-1]) - mean(
                value for _, value, _ in buckets[0]
            )
        results.append(
            SignalPeriodResult(
                period=period,
                window=window,
                sample_size=len(pairs),
                information_coefficient=information_coefficient,
                long_short_mean=long_short_mean,
            )
        )
    return results


def _apply_benjamini_hochberg(results: list[SignalWindowResult]) -> None:
    """Benjamini-Hochberg step-up adjustment of the long-short p-values across
    the tested windows. Without it, one window clearing 0.05 by chance (out of
    several tested) reads as a finding when it is just multiple comparisons."""
    tested = [
        (index, result.long_short_p_value)
        for index, result in enumerate(results)
        if result.long_short_p_value is not None
    ]
    ordered = sorted(tested, key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running = 1.0
    for rank, (index, p_value) in reversed(list(enumerate(ordered, start=1))):
        running = min(running, p_value * len(ordered) / rank)
        adjusted[index] = min(1.0, running)
    for index, value in adjusted.items():
        results[index].long_short_adjusted_p_value = value


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
        # The experiment key is invariant to market-data coverage (it fingerprints
        # the filing set, not which filings had bars), so a partial-coverage rerun
        # hits the same row. Never let it overwrite a study built on more events —
        # incremental Tiingo warming should only ever grow the published study.
        existing_events = int((experiment.results_json or {}).get("event_count", 0) or 0)
        if report.event_count < existing_events:
            return experiment
        experiment.config_json = report.config.model_dump(mode="json")
        experiment.results_json = payload
    session.commit()
    session.refresh(experiment)
    return experiment


def _summarize_window(
    window: str,
    pairs: list[SignalPair],
    n_quantiles: int,
    config: EventStudyConfig,
    rng: random.Random,
) -> SignalWindowResult:
    if len(pairs) < n_quantiles * 2:
        return SignalWindowResult(
            window=window,
            sample_size=len(pairs),
            cluster_count=len({cluster for _, _, cluster in pairs}),
            information_coefficient=None,
            ic_t_stat=None,
            quantiles=[],
            long_short_mean=None,
            long_short_ci_low=None,
            long_short_ci_high=None,
            long_short_p_value=None,
        )
    features = [feature for feature, _, _ in pairs]
    returns = [value for _, value, _ in pairs]
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
            mean_abnormal_return=(
                mean(value for _, value, _ in bucket) if bucket else None
            ),
        )
        for index, bucket in enumerate(buckets)
    ]
    low_returns = [(value, cluster) for _, value, cluster in buckets[0]]
    high_returns = [(value, cluster) for _, value, cluster in buckets[-1]]
    spread = mean(value for value, _ in high_returns) - mean(
        value for value, _ in low_returns
    )
    ci_low, ci_high, p_value = _bootstrap_difference(high_returns, low_returns, config, rng)
    return SignalWindowResult(
        window=window,
        sample_size=len(pairs),
        cluster_count=len({cluster for _, _, cluster in pairs}),
        information_coefficient=ic,
        ic_t_stat=ic_t,
        quantiles=quantiles,
        long_short_mean=spread,
        long_short_ci_low=ci_low,
        long_short_ci_high=ci_high,
        long_short_p_value=p_value,
    )


def _split_quantiles(
    ordered: list[SignalPair],
    n_quantiles: int,
) -> list[list[SignalPair]]:
    size = len(ordered)
    buckets: list[list[SignalPair]] = []
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
    high: list[tuple[float, str]],
    low: list[tuple[float, str]],
    config: EventStudyConfig,
    rng: random.Random,
) -> tuple[float | None, float | None, float | None]:
    if not high or not low:
        return None, None, None
    high_by_cluster: dict[str, list[float]] = defaultdict(list)
    low_by_cluster: dict[str, list[float]] = defaultdict(list)
    for value, cluster in high:
        high_by_cluster[cluster].append(value)
    for value, cluster in low:
        low_by_cluster[cluster].append(value)
    clusters = sorted(high_by_cluster.keys() | low_by_cluster.keys())
    if len(clusters) < 2:
        return None, None, None
    samples: list[float] = []
    for _ in range(config.bootstrap_iterations):
        sampled_clusters = rng.choices(clusters, k=len(clusters))
        sampled_high = [
            value for cluster in sampled_clusters for value in high_by_cluster[cluster]
        ]
        sampled_low = [
            value for cluster in sampled_clusters for value in low_by_cluster[cluster]
        ]
        if sampled_high and sampled_low:
            samples.append(mean(sampled_high) - mean(sampled_low))
    if not samples:
        return None, None, None
    samples.sort()
    alpha = 1 - config.confidence_level
    low_ci = samples[max(0, round((len(samples) - 1) * (alpha / 2)))]
    high_ci = samples[min(len(samples) - 1, round((len(samples) - 1) * (1 - alpha / 2)))]
    # The plus-one correction prevents an impossible reported p-value of zero
    # when no finite bootstrap draw crosses the null.
    below = (sum(sample <= 0 for sample in samples) + 1) / (len(samples) + 1)
    above = (sum(sample >= 0 for sample in samples) + 1) / (len(samples) + 1)
    return low_ci, high_ci, min(1.0, 2 * min(below, above))
