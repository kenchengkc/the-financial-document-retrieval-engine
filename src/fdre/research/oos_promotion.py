"""Final research promotion gate for sealed out-of-sample signal evidence.

A signal can reach this layer only after statistical and implementation review.
Promotion additionally requires predeclared robustness slices, transaction-cost
stress, horizon stability, and bounded single-name concentration. Missing
robustness evidence is reported as insufficient rather than treated as success.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.oos_diagnostics import OOSDiagnosticsReport, OOSWindowDiagnostic
from fdre.research.oos_implementation import (
    OOSImplementationRebalance,
    OOSImplementationReport,
    OOSImplementationWindowResult,
)
from fdre.research.oos_selection import OOSHypothesisDecision, OOSSelectionSuiteReport
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport

PromotionStatus = Literal["promote", "reject", "insufficient"]
_PROMOTION_VERSION = "sealed-oos-promotion-v1"


class OOSPromotionConfig(BaseModel):
    min_slice_observations_per_fold: int = Field(default=10, ge=3)
    min_slice_folds: int = Field(default=3, ge=1)
    min_analyzable_slices: int = Field(default=2, ge=0)
    min_positive_slice_share: float = Field(default=0.75, ge=0.0, le=1.0)
    stress_cost_bps: float = Field(default=50.0, ge=0.0)
    min_stress_net_mean: float = 0.0
    min_decay_horizons: int = Field(default=2, ge=1)
    min_positive_horizon_share: float = Field(default=0.67, ge=0.0, le=1.0)
    max_single_name_weight: float = Field(default=0.25, gt=0.0, le=1.0)


class OOSRobustnessSliceResult(BaseModel):
    name: str
    member_count: int
    observation_count: int
    fold_count: int
    analyzable: bool
    ic_mean: float | None
    positive_ic_share: float | None


class OOSSignalDecayPoint(BaseModel):
    window: str
    holding_period_sessions: int
    ic_mean: float | None


class OOSPromotionDecision(BaseModel):
    hypothesis_id: str
    signal_name: str
    window: str
    status: PromotionStatus
    reasons: list[str] = Field(default_factory=list)
    statistical_status: str
    implementation_status: str
    stress_cost_bps: float
    stress_net_mean: float | None
    max_single_name_weight: float | None
    analyzable_slice_count: int
    positive_slice_share: float | None
    robustness_slices: list[OOSRobustnessSliceResult] = Field(default_factory=list)
    signal_decay: list[OOSSignalDecayPoint] = Field(default_factory=list)
    positive_horizon_share: float | None
    live_trading_ready: bool = False


class OOSPromotionReport(BaseModel):
    promotion_key: str
    promotion_version: str = _PROMOTION_VERSION
    source_experiment_key: str
    source_diagnostics_key: str
    source_selection_key: str
    source_implementation_key: str
    slice_snapshot_id: str
    sealed_oos: bool = True
    config: OOSPromotionConfig
    decisions: list[OOSPromotionDecision]


def evaluate_oos_promotion(
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    *,
    slices: dict[str, set[str]] | None = None,
    config: OOSPromotionConfig | None = None,
) -> OOSPromotionReport:
    """Return final PROMOTE/REJECT/INSUFFICIENT research decisions."""
    if not source.sealed_oos or not diagnostics.sealed_oos or not implementation.sealed_oos:
        raise ValueError("final promotion requires sealed OOS artifacts")
    if diagnostics.source_experiment_key != source.experiment_key:
        raise ValueError("diagnostics do not belong to the supplied OOS experiment")
    if implementation.source_experiment_key != source.experiment_key:
        raise ValueError("implementation does not belong to the supplied OOS experiment")

    rules = config or OOSPromotionConfig()
    normalized_slices = {
        name: {ticker.upper() for ticker in members}
        for name, members in sorted((slices or {}).items())
    }
    slice_snapshot_id = _stable_digest(
        {name: sorted(members) for name, members in normalized_slices.items()}
    )
    implementation_by_hypothesis = {
        item.hypothesis_id: item for item in implementation.windows
    }
    diagnostics_by_window = {item.window: item for item in diagnostics.windows}

    decisions: list[OOSPromotionDecision] = []
    for statistical in selection.decisions:
        if statistical.source_experiment_key != source.experiment_key:
            continue
        implementation_result = implementation_by_hypothesis.get(statistical.hypothesis_id)
        if implementation_result is None:
            decisions.append(
                _upstream_missing_decision(statistical, rules, "implementation result missing")
            )
            continue
        decisions.append(
            _evaluate_decision(
                source,
                diagnostics_by_window,
                statistical,
                implementation_result,
                normalized_slices,
                rules,
            )
        )

    if not decisions:
        raise ValueError("selection suite has no hypotheses for the supplied experiment")
    promotion_key = _stable_digest(
        {
            "promotion_version": _PROMOTION_VERSION,
            "source_experiment_key": source.experiment_key,
            "source_diagnostics_key": diagnostics.diagnostics_key,
            "source_selection_key": selection.selection_key,
            "source_implementation_key": implementation.implementation_key,
            "slice_snapshot_id": slice_snapshot_id,
            "config": rules.model_dump(mode="json"),
        }
    )
    return OOSPromotionReport(
        promotion_key=promotion_key,
        source_experiment_key=source.experiment_key,
        source_diagnostics_key=diagnostics.diagnostics_key,
        source_selection_key=selection.selection_key,
        source_implementation_key=implementation.implementation_key,
        slice_snapshot_id=slice_snapshot_id,
        config=rules,
        decisions=decisions,
    )


def persist_oos_promotion(session: Session, report: OOSPromotionReport) -> ResearchExperiment:
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.promotion_key
        )
    )
    config_json = {
        "source_experiment_key": report.source_experiment_key,
        "source_diagnostics_key": report.source_diagnostics_key,
        "source_selection_key": report.source_selection_key,
        "source_implementation_key": report.source_implementation_key,
        "slice_snapshot_id": report.slice_snapshot_id,
        "promotion": report.config.model_dump(mode="json"),
    }
    payload = report.model_dump(mode="json")
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.promotion_key,
            experiment_type="oos_signal_promotion",
            dataset_version=f"walk-forward:{report.source_experiment_key}",
            feature_version=report.promotion_version,
            code_sha="derived-from-source-experiment",
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


def write_oos_promotion_report(path: str | Path, report: OOSPromotionReport) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _evaluate_decision(
    source: WalkForwardStudyReport,
    diagnostics_by_window: dict[str, OOSWindowDiagnostic],
    statistical: OOSHypothesisDecision,
    implementation: OOSImplementationWindowResult,
    slices: dict[str, set[str]],
    config: OOSPromotionConfig,
) -> OOSPromotionDecision:
    # Pydantic artifacts are intentionally accessed via validated attributes here;
    # local aliases keep this function compact without weakening public types.
    hypothesis_id = str(statistical.hypothesis_id)
    signal_name = str(statistical.signal_name)
    window = str(statistical.window)
    statistical_status = str(statistical.status)
    implementation_status = str(implementation.status)

    if statistical_status == "rejected" or implementation_status == "rejected":
        return _basic_decision(
            hypothesis_id,
            signal_name,
            window,
            "reject",
            statistical_status,
            implementation_status,
            config,
            ["an upstream sealed-OOS gate rejected the hypothesis"],
        )
    if (
        statistical_status != "passes_statistical_gate"
        or implementation_status != "passes_implementation_gate"
    ):
        return _basic_decision(
            hypothesis_id,
            signal_name,
            window,
            "insufficient",
            statistical_status,
            implementation_status,
            config,
            ["upstream evidence is insufficient for final promotion"],
        )

    robustness = [
        _slice_result(source.oos_observations, window, name, members, config)
        for name, members in slices.items()
    ]
    analyzable = [item for item in robustness if item.analyzable]
    positive_slice_share = (
        sum((item.ic_mean or 0.0) > 0 for item in analyzable) / len(analyzable)
        if analyzable
        else None
    )

    stress = next(
        (
            item
            for item in implementation.cost_scenarios
            if item.cost_bps == config.stress_cost_bps
        ),
        None,
    )
    stress_net_mean = stress.mean_net_return if stress is not None else None
    concentration = _max_single_name_weight(implementation.rebalances)
    decay = _signal_decay(diagnostics_by_window)
    valid_decay = [item for item in decay if item.ic_mean is not None]
    positive_horizon_share = (
        sum((item.ic_mean or 0.0) > 0 for item in valid_decay) / len(valid_decay)
        if valid_decay
        else None
    )

    insufficient: list[str] = []
    failures: list[str] = []
    if len(analyzable) < config.min_analyzable_slices:
        insufficient.append(
            f"analyzable robustness slices {len(analyzable)} < minimum "
            f"{config.min_analyzable_slices}"
        )
    elif positive_slice_share is None or positive_slice_share < config.min_positive_slice_share:
        failures.append("positive robustness-slice share is below the predeclared minimum")
    if stress is None or stress_net_mean is None:
        insufficient.append("predeclared transaction-cost stress scenario is unavailable")
    elif stress_net_mean <= config.min_stress_net_mean:
        failures.append("signal does not survive the predeclared transaction-cost stress")
    if concentration is None:
        insufficient.append("portfolio concentration could not be measured")
    elif concentration > config.max_single_name_weight:
        failures.append("single-name portfolio concentration exceeds the predeclared maximum")
    if len(valid_decay) < config.min_decay_horizons:
        insufficient.append(
            f"signal-decay horizons {len(valid_decay)} < minimum {config.min_decay_horizons}"
        )
    elif (
        positive_horizon_share is None
        or positive_horizon_share < config.min_positive_horizon_share
    ):
        failures.append("positive signal-decay horizon share is below the minimum")

    status: PromotionStatus
    reasons: list[str]
    if failures:
        status, reasons = "reject", failures + insufficient
    elif insufficient:
        status, reasons = "insufficient", insufficient
    else:
        status, reasons = "promote", []
    return OOSPromotionDecision(
        hypothesis_id=hypothesis_id,
        signal_name=signal_name,
        window=window,
        status=status,
        reasons=reasons,
        statistical_status=statistical_status,
        implementation_status=implementation_status,
        stress_cost_bps=config.stress_cost_bps,
        stress_net_mean=stress_net_mean,
        max_single_name_weight=concentration,
        analyzable_slice_count=len(analyzable),
        positive_slice_share=positive_slice_share,
        robustness_slices=robustness,
        signal_decay=decay,
        positive_horizon_share=positive_horizon_share,
    )


def _slice_result(
    observations: list[WalkForwardOOSObservation],
    window: str,
    name: str,
    members: set[str],
    config: OOSPromotionConfig,
) -> OOSRobustnessSliceResult:
    rows = [
        item
        for item in observations
        if item.window == window and item.ticker.upper() in members
    ]
    by_fold: dict[str, list[WalkForwardOOSObservation]] = defaultdict(list)
    for item in rows:
        by_fold[item.fold_id].append(item)
    fold_ics = [
        _spearman(
            [item.feature_value for item in fold_rows],
            [item.outcome_value for item in fold_rows],
        )
        for fold_rows in by_fold.values()
        if len(fold_rows) >= config.min_slice_observations_per_fold
    ]
    analyzable = len(fold_ics) >= config.min_slice_folds
    return OOSRobustnessSliceResult(
        name=name,
        member_count=len(members),
        observation_count=len(rows),
        fold_count=len(fold_ics),
        analyzable=analyzable,
        ic_mean=mean(fold_ics) if analyzable else None,
        positive_ic_share=(
            sum(value > 0 for value in fold_ics) / len(fold_ics)
            if analyzable
            else None
        ),
    )


def _signal_decay(
    diagnostics_by_window: dict[str, OOSWindowDiagnostic],
) -> list[OOSSignalDecayPoint]:
    points: list[OOSSignalDecayPoint] = []
    for window, result in diagnostics_by_window.items():
        try:
            start, end = _parse_window(window)
        except ValueError:
            continue
        points.append(
            OOSSignalDecayPoint(
                window=window,
                holding_period_sessions=end - start,
                ic_mean=result.ic_mean,
            )
        )
    return sorted(points, key=lambda item: (item.holding_period_sessions, item.window))


def _max_single_name_weight(
    rebalances: list[OOSImplementationRebalance],
) -> float | None:
    values: list[float] = []
    for item in rebalances:
        long_tickers = item.long_tickers
        short_tickers = item.short_tickers
        if long_tickers:
            values.append(1.0 / len(long_tickers))
        if short_tickers:
            values.append(1.0 / len(short_tickers))
    return max(values) if values else None


def _upstream_missing_decision(
    statistical: OOSHypothesisDecision,
    config: OOSPromotionConfig,
    reason: str,
) -> OOSPromotionDecision:
    return _basic_decision(
        str(statistical.hypothesis_id),
        str(statistical.signal_name),
        str(statistical.window),
        "insufficient",
        str(statistical.status),
        "missing",
        config,
        [reason],
    )


def _basic_decision(
    hypothesis_id: str,
    signal_name: str,
    window: str,
    status: PromotionStatus,
    statistical_status: str,
    implementation_status: str,
    config: OOSPromotionConfig,
    reasons: list[str],
) -> OOSPromotionDecision:
    return OOSPromotionDecision(
        hypothesis_id=hypothesis_id,
        signal_name=signal_name,
        window=window,
        status=status,
        reasons=reasons,
        statistical_status=statistical_status,
        implementation_status=implementation_status,
        stress_cost_bps=config.stress_cost_bps,
        stress_net_mean=None,
        max_single_name_weight=None,
        analyzable_slice_count=0,
        positive_slice_share=None,
        robustness_slices=[],
        signal_decay=[],
        positive_horizon_share=None,
    )


def _spearman(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_mean = mean(left_ranks)
    right_mean = mean(right_ranks)
    covariance = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left_ranks, right_ranks, strict=True)
    )
    left_scale = sum((value - left_mean) ** 2 for value in left_ranks) ** 0.5
    right_scale = sum((value - right_mean) ** 2 for value in right_ranks) ** 0.5
    if left_scale == 0 or right_scale == 0:
        return 0.0
    return covariance / (left_scale * right_scale)


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2
        for position in order[cursor:end]:
            ranks[position] = rank
        cursor = end
    return ranks


def _parse_window(window: str) -> tuple[int, int]:
    start_raw, end_raw = window.split(":", maxsplit=1)
    start, end = int(start_raw), int(end_raw)
    if end <= start:
        raise ValueError(f"invalid event window {window!r}")
    return start, end


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
