"""Implementation diagnostics for statistically eligible sealed-OOS signals.

This layer asks a narrower question than a backtest: if a statistically eligible
filing signal is converted into an event-cohort long/short book, how much of the
sealed OOS spread survives explicit turnover and transaction-cost assumptions?

The cohort construction is intentionally inspectable. Filing events are grouped
by calendar rebalance bucket, the latest event per issuer in that bucket is
ranked, and equal-weight top/bottom quantile legs are formed. Returns remain the
sealed event-aligned OOS outcomes produced upstream; this module never reopens
train/validation observations and never tunes the signal definition.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.oos_selection import (
    OOSHypothesisDecision,
    OOSSelectionSuiteReport,
)
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport

RebalanceFrequency = Literal["monthly", "quarterly"]
ImplementationStatus = Literal[
    "passes_implementation_gate",
    "rejected",
    "insufficient",
    "not_statistically_eligible",
]

_IMPLEMENTATION_VERSION = "sealed-oos-implementation-v1"


class OOSImplementationConfig(BaseModel):
    """Predeclared implementation assumptions for sealed OOS event cohorts."""

    n_quantiles: int = Field(default=5, ge=2)
    rebalance_frequency: RebalanceFrequency = "monthly"
    execution_delay_sessions: int = Field(default=1, ge=0)
    cost_bps: list[float] = Field(default_factory=lambda: [5.0, 10.0, 25.0, 50.0])
    evaluation_cost_bps: float = Field(default=25.0, ge=0.0)
    min_rebalance_issuers: int = Field(default=10, ge=2)
    min_rebalances: int = Field(default=3, ge=1)
    min_positive_net_fold_share: float = Field(default=0.60, ge=0.0, le=1.0)
    min_net_mean: float = 0.0
    max_annualized_turnover: float = Field(default=12.0, gt=0.0)

    @model_validator(mode="after")
    def validate_costs(self) -> OOSImplementationConfig:
        if not self.cost_bps:
            raise ValueError("at least one transaction-cost scenario is required")
        if any(value < 0 for value in self.cost_bps):
            raise ValueError("transaction-cost scenarios must be non-negative")
        if self.evaluation_cost_bps not in self.cost_bps:
            raise ValueError("evaluation_cost_bps must be included in cost_bps")
        return self


class OOSCostScenarioResult(BaseModel):
    cost_bps: float
    mean_net_return: float | None
    positive_rebalance_share: float | None
    positive_fold_share: float | None


class OOSImplementationRebalance(BaseModel):
    fold_id: str
    period: str
    window: str
    issuer_count: int
    long_tickers: list[str]
    short_tickers: list[str]
    gross_return: float
    turnover: float
    net_returns: dict[str, float]


class OOSImplementationWindowResult(BaseModel):
    hypothesis_id: str
    signal_name: str
    window: str
    status: ImplementationStatus
    reasons: list[str] = Field(default_factory=list)
    return_basis: str = "sealed_event_abnormal_returns"
    portfolio_mode: str = "latest_event_per_issuer_per_rebalance_bucket"
    capacity_status: str = "not_modeled"
    execution_delay_sessions: int
    holding_period_sessions: int | None
    rebalance_count: int
    fold_count: int
    mean_gross_return: float | None
    mean_turnover: float | None
    annualized_turnover: float | None
    cost_scenarios: list[OOSCostScenarioResult] = Field(default_factory=list)
    rebalances: list[OOSImplementationRebalance] = Field(default_factory=list)


class OOSImplementationReport(BaseModel):
    implementation_key: str
    implementation_version: str = _IMPLEMENTATION_VERSION
    source_experiment_key: str
    source_selection_key: str
    signal_name: str
    sealed_oos: bool = True
    deployment_ready: bool = False
    next_required_gate: str = "robustness_and_final_promotion"
    config: OOSImplementationConfig
    windows: list[OOSImplementationWindowResult]


def evaluate_oos_implementation(
    source: WalkForwardStudyReport,
    selection: OOSSelectionSuiteReport,
    config: OOSImplementationConfig | None = None,
) -> OOSImplementationReport:
    """Evaluate turnover/cost reality without reopening development observations."""
    if not source.sealed_oos:
        raise ValueError("implementation diagnostics require a sealed OOS study")
    implementation = config or OOSImplementationConfig()
    decisions = [
        decision
        for decision in selection.decisions
        if decision.source_experiment_key == source.experiment_key
    ]
    if not decisions:
        raise ValueError("selection suite contains no hypotheses for this OOS experiment")

    windows = [
        _evaluate_hypothesis(source, decision, implementation)
        for decision in sorted(decisions, key=lambda item: item.window)
    ]
    implementation_key = _stable_digest(
        {
            "implementation_version": _IMPLEMENTATION_VERSION,
            "source_experiment_key": source.experiment_key,
            "source_selection_key": selection.selection_key,
            "config": implementation.model_dump(mode="json"),
        }
    )
    return OOSImplementationReport(
        implementation_key=implementation_key,
        source_experiment_key=source.experiment_key,
        source_selection_key=selection.selection_key,
        signal_name=source.signal_name,
        config=implementation,
        windows=windows,
    )


def persist_oos_implementation(
    session: Session,
    report: OOSImplementationReport,
) -> ResearchExperiment:
    """Persist the implementation layer idempotently in the experiment store."""
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.implementation_key
        )
    )
    config_json = {
        "source_experiment_key": report.source_experiment_key,
        "source_selection_key": report.source_selection_key,
        "implementation": report.config.model_dump(mode="json"),
    }
    payload = report.model_dump(mode="json")
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.implementation_key,
            experiment_type="oos_signal_implementation",
            dataset_version=f"walk-forward:{report.source_experiment_key}",
            feature_version=report.implementation_version,
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


def write_oos_implementation_report(
    path: str | Path,
    report: OOSImplementationReport,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _evaluate_hypothesis(
    source: WalkForwardStudyReport,
    decision: OOSHypothesisDecision,
    config: OOSImplementationConfig,
) -> OOSImplementationWindowResult:
    start, end = _parse_window(decision.window)
    holding_period = end - start
    if decision.status != "passes_statistical_gate":
        return _empty_window(
            decision,
            config,
            holding_period,
            "not_statistically_eligible",
            ["hypothesis did not pass the sealed-OOS statistical gate"],
        )
    if start < config.execution_delay_sessions:
        return _empty_window(
            decision,
            config,
            holding_period,
            "insufficient",
            [
                "sealed outcome window begins before the predeclared execution delay; "
                "a later-start outcome must be evaluated upstream"
            ],
        )

    observations = [
        observation
        for observation in source.oos_observations
        if observation.window == decision.window
    ]
    for observation in observations:
        if observation.max_source_available_at > observation.available_at:
            raise ValueError(
                f"implementation leakage for {observation.accession_number}: source data "
                "was not available at the filing decision time"
            )

    grouped: dict[tuple[str, str], list[WalkForwardOOSObservation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.fold_id, _period_key(observation, config))].append(observation)

    rebalances: list[OOSImplementationRebalance] = []
    prior_weights: dict[str, float] = {}
    for (fold_id, period), bucket in sorted(grouped.items(), key=lambda item: item[0][1]):
        latest = _latest_per_issuer(bucket)
        if len(latest) < config.min_rebalance_issuers:
            continue
        quantiles = _split_observations(latest, config.n_quantiles)
        if not quantiles or not quantiles[0] or not quantiles[-1]:
            continue
        short = quantiles[0]
        long = quantiles[-1]
        weights = _long_short_weights(long, short)
        gross_return = sum(
            weights[item.ticker.upper()] * item.outcome_value for item in [*long, *short]
        )
        turnover = _turnover(prior_weights, weights)
        net_returns = {
            _cost_key(cost): gross_return - turnover * cost / 10_000.0
            for cost in sorted(set(config.cost_bps))
        }
        rebalances.append(
            OOSImplementationRebalance(
                fold_id=fold_id,
                period=period,
                window=decision.window,
                issuer_count=len(latest),
                long_tickers=sorted(item.ticker.upper() for item in long),
                short_tickers=sorted(item.ticker.upper() for item in short),
                gross_return=gross_return,
                turnover=turnover,
                net_returns=net_returns,
            )
        )
        prior_weights = weights

    if len(rebalances) < config.min_rebalances:
        return _empty_window(
            decision,
            config,
            holding_period,
            "insufficient",
            [
                f"eligible rebalances {len(rebalances)} < minimum "
                f"{config.min_rebalances}"
            ],
            rebalances=rebalances,
        )

    mean_turnover = mean(item.turnover for item in rebalances)
    annualized_turnover = mean_turnover * _periods_per_year(config.rebalance_frequency)
    scenarios = [
        _cost_scenario(cost, rebalances) for cost in sorted(set(config.cost_bps))
    ]
    evaluation = next(
        item for item in scenarios if item.cost_bps == config.evaluation_cost_bps
    )
    reasons: list[str] = []
    if evaluation.mean_net_return is None or evaluation.mean_net_return <= config.min_net_mean:
        reasons.append("mean cost-adjusted OOS return is not positive enough")
    if (
        evaluation.positive_fold_share is None
        or evaluation.positive_fold_share < config.min_positive_net_fold_share
    ):
        reasons.append("positive cost-adjusted fold share is below the minimum")
    if annualized_turnover > config.max_annualized_turnover:
        reasons.append("annualized turnover exceeds the predeclared maximum")
    status: ImplementationStatus = "rejected" if reasons else "passes_implementation_gate"

    return OOSImplementationWindowResult(
        hypothesis_id=decision.hypothesis_id,
        signal_name=decision.signal_name,
        window=decision.window,
        status=status,
        reasons=reasons,
        execution_delay_sessions=config.execution_delay_sessions,
        holding_period_sessions=holding_period,
        rebalance_count=len(rebalances),
        fold_count=len({item.fold_id for item in rebalances}),
        mean_gross_return=mean(item.gross_return for item in rebalances),
        mean_turnover=mean_turnover,
        annualized_turnover=annualized_turnover,
        cost_scenarios=scenarios,
        rebalances=rebalances,
    )


def _empty_window(
    decision: OOSHypothesisDecision,
    config: OOSImplementationConfig,
    holding_period: int | None,
    status: ImplementationStatus,
    reasons: list[str],
    *,
    rebalances: list[OOSImplementationRebalance] | None = None,
) -> OOSImplementationWindowResult:
    rows = rebalances or []
    return OOSImplementationWindowResult(
        hypothesis_id=decision.hypothesis_id,
        signal_name=decision.signal_name,
        window=decision.window,
        status=status,
        reasons=reasons,
        execution_delay_sessions=config.execution_delay_sessions,
        holding_period_sessions=holding_period,
        rebalance_count=len(rows),
        fold_count=len({item.fold_id for item in rows}),
        mean_gross_return=None,
        mean_turnover=None,
        annualized_turnover=None,
        cost_scenarios=[],
        rebalances=rows,
    )


def _latest_per_issuer(
    observations: list[WalkForwardOOSObservation],
) -> list[WalkForwardOOSObservation]:
    latest: dict[str, WalkForwardOOSObservation] = {}
    for observation in sorted(
        observations,
        key=lambda item: (item.event_session, item.accession_number),
    ):
        latest[observation.ticker.upper()] = observation
    return sorted(
        latest.values(),
        key=lambda item: (item.feature_value, item.ticker.upper(), item.accession_number),
    )


def _split_observations(
    observations: list[WalkForwardOOSObservation],
    n_quantiles: int,
) -> list[list[WalkForwardOOSObservation]]:
    if len(observations) < n_quantiles:
        return []
    base, remainder = divmod(len(observations), n_quantiles)
    buckets: list[list[WalkForwardOOSObservation]] = []
    cursor = 0
    for index in range(n_quantiles):
        size = base + (1 if index < remainder else 0)
        buckets.append(observations[cursor : cursor + size])
        cursor += size
    return buckets


def _long_short_weights(
    long: list[WalkForwardOOSObservation],
    short: list[WalkForwardOOSObservation],
) -> dict[str, float]:
    weights = {item.ticker.upper(): 1.0 / len(long) for item in long}
    weights.update({item.ticker.upper(): -1.0 / len(short) for item in short})
    return weights


def _turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    tickers = set(previous) | set(current)
    return 0.5 * sum(abs(current.get(ticker, 0.0) - previous.get(ticker, 0.0)) for ticker in tickers)


def _cost_scenario(
    cost_bps: float,
    rebalances: list[OOSImplementationRebalance],
) -> OOSCostScenarioResult:
    key = _cost_key(cost_bps)
    values = [item.net_returns[key] for item in rebalances]
    by_fold: dict[str, list[float]] = defaultdict(list)
    for item in rebalances:
        by_fold[item.fold_id].append(item.net_returns[key])
    fold_means = [mean(items) for items in by_fold.values()]
    return OOSCostScenarioResult(
        cost_bps=cost_bps,
        mean_net_return=mean(values) if values else None,
        positive_rebalance_share=(
            sum(value > 0 for value in values) / len(values) if values else None
        ),
        positive_fold_share=(
            sum(value > 0 for value in fold_means) / len(fold_means)
            if fold_means
            else None
        ),
    )


def _parse_window(window: str) -> tuple[int, int]:
    try:
        start_raw, end_raw = window.split(":", maxsplit=1)
        start, end = int(start_raw), int(end_raw)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"invalid event window {window!r}") from error
    if end <= start:
        raise ValueError(f"invalid event window {window!r}")
    return start, end


def _period_key(
    observation: WalkForwardOOSObservation,
    config: OOSImplementationConfig,
) -> str:
    day = observation.event_session
    if config.rebalance_frequency == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    quarter = (day.month - 1) // 3 + 1
    return f"{day.year:04d}-Q{quarter}"


def _periods_per_year(frequency: RebalanceFrequency) -> int:
    return 12 if frequency == "monthly" else 4


def _cost_key(value: float) -> str:
    return f"{value:g}bps"


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
