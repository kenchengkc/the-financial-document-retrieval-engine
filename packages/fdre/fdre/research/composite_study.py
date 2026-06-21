"""Composite (multi-signal) study.

Combines several weak, point-in-time filing signals into one cross-sectionally
standardized score and measures whether the combination carries more
information than any single signal — the Fundamental Law of Active Management
(IR ~ IC * sqrt(breadth)) made concrete. Each signal is z-scored within its
filing period (period/level-neutral) and sign-aligned so that a higher score
predicts a higher forward return, then averaged.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime
from statistics import fmean, pstdev

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import EventStudyConfig, FilingEvent, MarketBar, run_event_study
from fdre.research.signal_study import (
    SignalStudyReport,
    _apply_benjamini_hochberg,
    _spearman,
    _summarize_window,
)


class SignalComponent(BaseModel):
    """One raw signal: how to read it from a panel row and which sign predicts
    a higher forward return (+1 = higher value bullish, -1 = bearish)."""

    name: str
    sign: int = 1


class ComponentResult(BaseModel):
    signal: str
    window: str
    sample_size: int
    information_coefficient: float | None


class SignalCorrelation(BaseModel):
    signal_a: str
    signal_b: str
    correlation: float | None


class CompositeStudyReport(SignalStudyReport):
    component_signals: list[str]
    components: list[ComponentResult]
    signal_correlations: list[SignalCorrelation]


class CompositeEvent(BaseModel):
    ticker: str
    accession_number: str
    available_at_period: str
    available_at: datetime
    max_source_available_at: datetime
    raw: dict[str, float]


def standardize_by_period(
    events: list[CompositeEvent],
    components: list[SignalComponent],
) -> dict[str, dict[str, float]]:
    """Return accession -> {signal: sign-aligned z-score within its period}."""
    by_period_signal: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for event in events:
        for component in components:
            value = event.raw.get(component.name)
            if value is not None:
                by_period_signal[(event.available_at_period, component.name)].append(
                    (event.accession_number, value)
                )
    z: dict[str, dict[str, float]] = defaultdict(dict)
    for (_, signal), rows in by_period_signal.items():
        values = [value for _, value in rows]
        if len(values) < 2:
            continue
        mean = fmean(values)
        std = pstdev(values)
        if std == 0:
            continue
        sign = next(c.sign for c in components if c.name == signal)
        for accession, value in rows:
            z[accession][signal] = sign * (value - mean) / std
    return z


def run_composite_study(
    events: list[CompositeEvent],
    components: list[SignalComponent],
    bars: list[MarketBar],
    config: EventStudyConfig,
    *,
    n_quantiles: int,
    dataset_version: str,
    feature_version: str,
    code_sha: str,
) -> CompositeStudyReport:
    z = standardize_by_period(events, components)
    composite_value: dict[str, float] = {}
    for accession, signals in z.items():
        if signals:
            composite_value[accession] = fmean(signals.values())

    filing_events = [
        FilingEvent(
            ticker=event.ticker,
            accession_number=event.accession_number,
            available_at=event.available_at,
            max_source_available_at=event.max_source_available_at,
            feature_value=composite_value.get(event.accession_number),
        )
        for event in events
        if event.accession_number in composite_value
    ]
    base = run_event_study(
        filing_events,
        bars,
        config,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
    )

    # composite per-window summary
    composite_by_window: dict[str, list[tuple[float, float]]] = defaultdict(list)
    abnormal_by_window: dict[str, dict[str, float]] = defaultdict(dict)
    for observation in base.observations:
        feature = composite_value.get(observation.accession_number)
        if feature is not None:
            composite_by_window[observation.window].append(
                (feature, observation.abnormal_return)
            )
        abnormal_by_window[observation.window][observation.accession_number] = (
            observation.abnormal_return
        )
    rng = random.Random(config.random_seed)
    results = [
        _summarize_window(
            window.label, composite_by_window.get(window.label, []), n_quantiles, config, rng
        )
        for window in config.windows
    ]
    _apply_benjamini_hochberg(results)

    # per-component IC per window
    components_out: list[ComponentResult] = []
    for window in config.windows:
        abnormal = abnormal_by_window.get(window.label, {})
        for component in [*components, SignalComponent(name="composite", sign=1)]:
            pairs: list[tuple[float, float]] = []
            for accession, ret in abnormal.items():
                value = (
                    composite_value.get(accession)
                    if component.name == "composite"
                    else z.get(accession, {}).get(component.name)
                )
                if value is not None:
                    pairs.append((value, ret))
            ic = (
                _spearman([a for a, _ in pairs], [b for _, b in pairs])
                if len(pairs) >= 3
                else None
            )
            components_out.append(
                ComponentResult(
                    signal=component.name,
                    window=window.label,
                    sample_size=len(pairs),
                    information_coefficient=ic,
                )
            )

    correlations = _signal_correlations(z, [c.name for c in components])

    manifest = {
        "signal_name": "composite",
        "components": [c.name for c in components],
        "n_quantiles": n_quantiles,
        "dataset_version": dataset_version,
        "feature_version": feature_version,
        "code_sha": code_sha,
        "config": config.model_dump(mode="json"),
        "events": sorted(composite_value),
    }
    experiment_key = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CompositeStudyReport(
        experiment_key=experiment_key,
        signal_name="composite",
        outcome_name="abnormal_return",
        n_quantiles=n_quantiles,
        dataset_version=dataset_version,
        feature_version=feature_version,
        code_sha=code_sha,
        config=config,
        event_count=base.event_count,
        results=results,
        component_signals=[c.name for c in components],
        components=components_out,
        signal_correlations=correlations,
    )


def _signal_correlations(
    z: dict[str, dict[str, float]],
    signals: list[str],
) -> list[SignalCorrelation]:
    out: list[SignalCorrelation] = []
    for i, signal_a in enumerate(signals):
        for signal_b in signals[i + 1 :]:
            paired = [
                (row[signal_a], row[signal_b])
                for row in z.values()
                if signal_a in row and signal_b in row
            ]
            correlation = (
                _spearman([a for a, _ in paired], [b for _, b in paired])
                if len(paired) >= 3
                else None
            )
            out.append(
                SignalCorrelation(signal_a=signal_a, signal_b=signal_b, correlation=correlation)
            )
    return out


def persist_composite_study(
    session: Session,
    report: CompositeStudyReport,
) -> ResearchExperiment:
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
        experiment.results_json = payload
    session.commit()
    session.refresh(experiment)
    return experiment


def period_label(value: date) -> str:
    return f"{value.year}Q{(value.month - 1) // 3 + 1}"
