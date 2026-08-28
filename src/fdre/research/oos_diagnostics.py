"""Diagnostics computed exclusively from sealed walk-forward OOS observations.

This layer is descriptive by design. It does not tune signal parameters, select
horizons, or promote/reject a signal. Every statistic is derived from the test
observations already admitted by :mod:`fdre.research.walk_forward`.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.signal_study import SignalPair, _spearman, _split_quantiles
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport

FoldDiagnosticsStatus = Literal["ready", "insufficient_breadth"]
OOSDiagnosticsStatus = Literal["ready", "insufficient_oos_data"]


class OOSDiagnosticsConfig(BaseModel):
    """Reporting sufficiency rules; these never alter the sealed OOS sample."""

    n_quantiles: int = Field(default=5, ge=2)
    min_fold_observations: int = Field(default=10, ge=3)
    min_issuer_count: int = Field(default=5, ge=2)
    min_stability_folds: int = Field(default=3, ge=2)


class OOSQuantileResult(BaseModel):
    quantile: int = Field(ge=1)
    sample_size: int = Field(ge=0)
    mean_outcome: float | None


class OOSFoldWindowDiagnostic(BaseModel):
    fold_id: str
    window: str
    status: FoldDiagnosticsStatus
    insufficiency_reasons: list[str] = Field(default_factory=list)
    sample_size: int
    issuer_count: int
    information_coefficient: float | None
    quantiles: list[OOSQuantileResult] = Field(default_factory=list)
    quantile_monotonicity: float | None
    long_short_mean: float | None


class OOSWindowDiagnostic(BaseModel):
    window: str
    observed_fold_count: int
    analyzable_fold_count: int
    observation_count: int
    issuer_count: int
    minimum_fold_sample_size: int | None
    minimum_fold_issuer_count: int | None
    ic_fold_count: int
    ic_mean: float | None
    ic_std: float | None
    icir: float | None
    positive_ic_share: float | None
    quantile_monotonicity_fold_count: int
    quantile_monotonicity_mean: float | None
    long_short_fold_count: int
    long_short_mean: float | None
    positive_long_short_share: float | None
    stability_ready: bool


class OOSDiagnosticsReport(BaseModel):
    diagnostics_key: str
    source_experiment_key: str
    signal_name: str
    outcome_name: str
    sealed_oos: bool = True
    promotion_status: str = "not_evaluated"
    status: OOSDiagnosticsStatus
    dataset_version: str
    feature_version: str
    market_data_version: str
    universe_snapshot_id: str
    feature_snapshot_id: str
    code_sha: str
    source_eligible_fold_count: int
    source_oos_event_count: int
    source_oos_observation_count: int
    config: OOSDiagnosticsConfig
    warnings: list[str] = Field(default_factory=list)
    windows: list[OOSWindowDiagnostic] = Field(default_factory=list)
    folds: list[OOSFoldWindowDiagnostic] = Field(default_factory=list)


def build_oos_diagnostics(
    source: WalkForwardStudyReport,
    config: OOSDiagnosticsConfig | None = None,
) -> OOSDiagnosticsReport:
    """Summarize sealed OOS observations without reopening development data."""
    if not source.sealed_oos:
        raise ValueError("OOS diagnostics require a sealed walk-forward study")

    reporting = config or OOSDiagnosticsConfig()
    grouped: dict[tuple[str, str], list[WalkForwardOOSObservation]] = defaultdict(list)
    for observation in source.oos_observations:
        grouped[(observation.fold_id, observation.window)].append(observation)

    fold_results = [
        _summarize_fold_window(fold_id, window, observations, reporting)
        for (fold_id, window), observations in sorted(grouped.items())
    ]
    observations_by_window: dict[str, list[WalkForwardOOSObservation]] = defaultdict(list)
    folds_by_window: dict[str, list[OOSFoldWindowDiagnostic]] = defaultdict(list)
    for observation in source.oos_observations:
        observations_by_window[observation.window].append(observation)
    for result in fold_results:
        folds_by_window[result.window].append(result)

    windows = [
        _summarize_window(
            window,
            observations_by_window[window],
            folds_by_window[window],
            reporting,
        )
        for window in sorted(observations_by_window)
    ]
    warnings = _diagnostic_warnings(source, windows, reporting)
    status: OOSDiagnosticsStatus = (
        "ready" if any(window.stability_ready for window in windows) else "insufficient_oos_data"
    )
    diagnostics_key = _stable_digest(
        {
            "source_experiment_key": source.experiment_key,
            "config": reporting.model_dump(mode="json"),
            "diagnostics_version": "sealed-oos-diagnostics-v1",
        }
    )
    return OOSDiagnosticsReport(
        diagnostics_key=diagnostics_key,
        source_experiment_key=source.experiment_key,
        signal_name=source.signal_name,
        outcome_name=source.outcome_name,
        status=status,
        dataset_version=source.dataset_version,
        feature_version=source.feature_version,
        market_data_version=source.market_data_version,
        universe_snapshot_id=source.universe_snapshot_id,
        feature_snapshot_id=source.feature_snapshot_id,
        code_sha=source.code_sha,
        source_eligible_fold_count=source.eligible_fold_count,
        source_oos_event_count=source.oos_event_count,
        source_oos_observation_count=source.oos_observation_count,
        config=reporting,
        warnings=warnings,
        windows=windows,
        folds=fold_results,
    )


def persist_oos_diagnostics(
    session: Session,
    report: OOSDiagnosticsReport,
) -> ResearchExperiment:
    """Persist an immutable-by-key diagnostic view in the experiment registry."""
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.diagnostics_key
        )
    )
    config_json = {
        "source_experiment_key": report.source_experiment_key,
        "diagnostics": report.config.model_dump(mode="json"),
    }
    payload = report.model_dump(mode="json")
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.diagnostics_key,
            experiment_type="oos_signal_diagnostics",
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


def write_oos_diagnostics_report(
    path: str | Path,
    report: OOSDiagnosticsReport,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _summarize_fold_window(
    fold_id: str,
    window: str,
    observations: list[WalkForwardOOSObservation],
    config: OOSDiagnosticsConfig,
) -> OOSFoldWindowDiagnostic:
    ordered_observations = sorted(
        observations,
        key=lambda item: (item.event_session, item.ticker.upper(), item.accession_number),
    )
    issuer_count = len({item.ticker.upper() for item in ordered_observations})
    reasons: list[str] = []
    if len(ordered_observations) < config.min_fold_observations:
        reasons.append(
            f"observations {len(ordered_observations)} < minimum {config.min_fold_observations}"
        )
    if issuer_count < config.min_issuer_count:
        reasons.append(f"issuers {issuer_count} < minimum {config.min_issuer_count}")
    if reasons:
        return OOSFoldWindowDiagnostic(
            fold_id=fold_id,
            window=window,
            status="insufficient_breadth",
            insufficiency_reasons=reasons,
            sample_size=len(ordered_observations),
            issuer_count=issuer_count,
            information_coefficient=None,
            quantiles=[],
            quantile_monotonicity=None,
            long_short_mean=None,
        )

    pairs: list[SignalPair] = [
        (item.feature_value, item.outcome_value, item.ticker.upper())
        for item in ordered_observations
    ]
    information_coefficient = _spearman(
        [feature for feature, _, _ in pairs],
        [outcome for _, outcome, _ in pairs],
    )
    quantiles: list[OOSQuantileResult] = []
    quantile_monotonicity: float | None = None
    long_short_mean: float | None = None
    if len(pairs) >= config.n_quantiles * 2:
        buckets = _split_quantiles(sorted(pairs, key=lambda item: item[0]), config.n_quantiles)
        quantiles = [
            OOSQuantileResult(
                quantile=index + 1,
                sample_size=len(bucket),
                mean_outcome=mean(value for _, value, _ in bucket) if bucket else None,
            )
            for index, bucket in enumerate(buckets)
        ]
        means = [item.mean_outcome for item in quantiles]
        if all(value is not None for value in means):
            quantile_monotonicity = _spearman(
                [float(index + 1) for index in range(len(means))],
                [float(value) for value in means if value is not None],
            )
        if buckets[0] and buckets[-1]:
            long_short_mean = mean(value for _, value, _ in buckets[-1]) - mean(
                value for _, value, _ in buckets[0]
            )

    return OOSFoldWindowDiagnostic(
        fold_id=fold_id,
        window=window,
        status="ready",
        sample_size=len(ordered_observations),
        issuer_count=issuer_count,
        information_coefficient=information_coefficient,
        quantiles=quantiles,
        quantile_monotonicity=quantile_monotonicity,
        long_short_mean=long_short_mean,
    )


def _summarize_window(
    window: str,
    observations: list[WalkForwardOOSObservation],
    folds: list[OOSFoldWindowDiagnostic],
    config: OOSDiagnosticsConfig,
) -> OOSWindowDiagnostic:
    analyzable = [fold for fold in folds if fold.status == "ready"]
    ic_values = [
        fold.information_coefficient
        for fold in analyzable
        if fold.information_coefficient is not None
    ]
    monotonicity_values = [
        fold.quantile_monotonicity
        for fold in analyzable
        if fold.quantile_monotonicity is not None
    ]
    spread_values = [
        fold.long_short_mean for fold in analyzable if fold.long_short_mean is not None
    ]
    ic_mean = mean(ic_values) if ic_values else None
    ic_std = stdev(ic_values) if len(ic_values) >= 2 else None
    icir = (
        ic_mean / ic_std
        if ic_mean is not None and ic_std is not None and ic_std > 0
        else None
    )
    return OOSWindowDiagnostic(
        window=window,
        observed_fold_count=len(folds),
        analyzable_fold_count=len(analyzable),
        observation_count=len(observations),
        issuer_count=len({item.ticker.upper() for item in observations}),
        minimum_fold_sample_size=min((fold.sample_size for fold in folds), default=None),
        minimum_fold_issuer_count=min((fold.issuer_count for fold in folds), default=None),
        ic_fold_count=len(ic_values),
        ic_mean=ic_mean,
        ic_std=ic_std,
        icir=icir,
        positive_ic_share=(
            sum(value > 0 for value in ic_values) / len(ic_values) if ic_values else None
        ),
        quantile_monotonicity_fold_count=len(monotonicity_values),
        quantile_monotonicity_mean=(
            mean(monotonicity_values) if monotonicity_values else None
        ),
        long_short_fold_count=len(spread_values),
        long_short_mean=mean(spread_values) if spread_values else None,
        positive_long_short_share=(
            sum(value > 0 for value in spread_values) / len(spread_values)
            if spread_values
            else None
        ),
        stability_ready=len(ic_values) >= config.min_stability_folds,
    )


def _diagnostic_warnings(
    source: WalkForwardStudyReport,
    windows: list[OOSWindowDiagnostic],
    config: OOSDiagnosticsConfig,
) -> list[str]:
    warnings: list[str] = []
    if not source.oos_observations:
        warnings.append("sealed OOS sample contains no observations")
    for window in windows:
        if not window.stability_ready:
            warnings.append(
                f"{window.window}: {window.ic_fold_count} analyzable IC folds < "
                f"minimum {config.min_stability_folds} for stability diagnostics"
            )
        if window.analyzable_fold_count < window.observed_fold_count:
            warnings.append(
                f"{window.window}: {window.observed_fold_count - window.analyzable_fold_count} "
                "observed fold(s) suppressed for insufficient cross-sectional breadth"
            )
    return warnings


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
