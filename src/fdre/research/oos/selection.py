"""Multiple-testing-aware statistical gates for sealed OOS signal diagnostics.

A pass here means only that a predeclared signal/horizon has enough sealed OOS
rank evidence to remain a research candidate. It is deliberately not a trading
or deployment verdict: turnover, transaction costs, robustness, and decay are
separate downstream gates.
"""

from __future__ import annotations

import hashlib
import json
from math import erfc, sqrt
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.oos_diagnostics import OOSDiagnosticsReport, OOSWindowDiagnostic

OOSSelectionStatus = Literal["passes_statistical_gate", "rejected", "insufficient"]

_MAX_EXACT_SIGN_FLIP_FOLDS = 20
_SELECTION_VERSION = "sealed-oos-statistical-gate-v1"


class OOSSelectionConfig(BaseModel):
    """Predeclared thresholds for the sealed-OOS statistical evidence gate."""

    min_ic_folds: int = Field(default=4, ge=2)
    min_ic_mean: float = 0.02
    min_icir: float = 0.50
    min_positive_ic_share: float = Field(default=0.65, ge=0.0, le=1.0)
    min_quantile_monotonicity: float = Field(default=0.50, ge=-1.0, le=1.0)
    min_positive_long_short_share: float = Field(default=0.60, ge=0.0, le=1.0)
    min_long_short_mean: float = 0.0
    max_fdr_q_value: float = Field(default=0.10, gt=0.0, le=1.0)


class OOSHypothesisDecision(BaseModel):
    hypothesis_id: str
    source_diagnostics_key: str
    source_experiment_key: str
    signal_name: str
    outcome_name: str
    window: str
    status: OOSSelectionStatus
    reasons: list[str] = Field(default_factory=list)
    ic_fold_count: int
    ic_mean: float | None
    icir: float | None
    positive_ic_share: float | None
    quantile_monotonicity_mean: float | None
    long_short_mean: float | None
    positive_long_short_share: float | None
    raw_p_value: float | None
    adjusted_q_value: float | None
    inference_method: str | None


class OOSSelectionSuiteReport(BaseModel):
    selection_key: str
    selection_version: str = _SELECTION_VERSION
    selection_scope: str = "statistical_evidence_only"
    deployment_ready: bool = False
    next_required_gate: str = "turnover_and_transaction_costs"
    multiple_testing_method: str = (
        "Benjamini-Hochberg over the predeclared signal x horizon family; "
        "one-sided fold-IC sign-flip p-values"
    )
    declared_hypothesis_count: int
    tested_hypothesis_count: int
    passing_count: int
    rejected_count: int
    insufficient_count: int
    input_diagnostics_keys: list[str]
    source_code_digest: str
    config: OOSSelectionConfig
    decisions: list[OOSHypothesisDecision]


class _HypothesisEvidence(BaseModel):
    hypothesis_id: str
    source_diagnostics_key: str
    source_experiment_key: str
    signal_name: str
    outcome_name: str
    window: str
    ic_fold_count: int
    ic_mean: float | None
    icir: float | None
    positive_ic_share: float | None
    quantile_monotonicity_mean: float | None
    long_short_mean: float | None
    positive_long_short_share: float | None
    raw_p_value: float | None
    inference_method: str | None
    insufficiency_reasons: list[str] = Field(default_factory=list)


def evaluate_oos_selection_suite(
    diagnostics: list[OOSDiagnosticsReport],
    config: OOSSelectionConfig | None = None,
) -> OOSSelectionSuiteReport:
    """Apply predeclared statistical gates to a family of sealed OOS hypotheses."""
    if not diagnostics:
        raise ValueError("OOS selection suite requires at least one diagnostics report")
    if any(not report.sealed_oos for report in diagnostics):
        raise ValueError("OOS selection suite accepts only sealed diagnostics")

    selection = config or OOSSelectionConfig()
    evidence: list[_HypothesisEvidence] = []
    seen_hypotheses: set[str] = set()
    for report in sorted(diagnostics, key=lambda item: item.diagnostics_key):
        for window in sorted(report.windows, key=lambda item: item.window):
            hypothesis = _build_hypothesis_evidence(report, window, selection)
            if hypothesis.hypothesis_id in seen_hypotheses:
                raise ValueError(f"duplicate OOS hypothesis {hypothesis.hypothesis_id}")
            seen_hypotheses.add(hypothesis.hypothesis_id)
            evidence.append(hypothesis)

    declared_count = len(evidence)
    adjusted = _benjamini_hochberg(
        {
            item.hypothesis_id: item.raw_p_value
            for item in evidence
            if item.raw_p_value is not None
        },
        family_size=declared_count,
    )
    decisions = [
        _decision(item, adjusted.get(item.hypothesis_id), selection) for item in evidence
    ]
    decisions.sort(key=lambda item: (item.signal_name, item.outcome_name, item.window))

    input_keys = sorted(report.diagnostics_key for report in diagnostics)
    source_code_digest = _stable_digest(sorted({report.code_sha for report in diagnostics}))
    selection_key = _stable_digest(
        {
            "selection_version": _SELECTION_VERSION,
            "input_diagnostics_keys": input_keys,
            "config": selection.model_dump(mode="json"),
        }
    )
    return OOSSelectionSuiteReport(
        selection_key=selection_key,
        declared_hypothesis_count=declared_count,
        tested_hypothesis_count=sum(item.raw_p_value is not None for item in evidence),
        passing_count=sum(item.status == "passes_statistical_gate" for item in decisions),
        rejected_count=sum(item.status == "rejected" for item in decisions),
        insufficient_count=sum(item.status == "insufficient" for item in decisions),
        input_diagnostics_keys=input_keys,
        source_code_digest=source_code_digest,
        config=selection,
        decisions=decisions,
    )


def persist_oos_selection_suite(
    session: Session,
    report: OOSSelectionSuiteReport,
) -> ResearchExperiment:
    """Persist the reproducible suite decision in the generic experiment registry."""
    experiment = session.scalar(
        select(ResearchExperiment).where(
            ResearchExperiment.experiment_key == report.selection_key
        )
    )
    config_json = {
        "selection_version": report.selection_version,
        "selection_scope": report.selection_scope,
        "input_diagnostics_keys": report.input_diagnostics_keys,
        "config": report.config.model_dump(mode="json"),
    }
    payload = report.model_dump(mode="json")
    dataset_version = "suite:" + _stable_digest(report.input_diagnostics_keys)
    if experiment is None:
        experiment = ResearchExperiment(
            experiment_key=report.selection_key,
            experiment_type="oos_signal_selection_suite",
            dataset_version=dataset_version,
            feature_version=_SELECTION_VERSION,
            code_sha=report.source_code_digest,
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


def write_oos_selection_report(
    path: str | Path,
    report: OOSSelectionSuiteReport,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return destination


def _build_hypothesis_evidence(
    report: OOSDiagnosticsReport,
    window: OOSWindowDiagnostic,
    config: OOSSelectionConfig,
) -> _HypothesisEvidence:
    hypothesis_id = _stable_digest(
        {
            "source_experiment_key": report.source_experiment_key,
            "signal_name": report.signal_name,
            "outcome_name": report.outcome_name,
            "window": window.window,
        }
    )
    fold_ics = [
        fold.information_coefficient
        for fold in report.folds
        if fold.window == window.window
        and fold.status == "ready"
        and fold.information_coefficient is not None
    ]
    if len(fold_ics) != window.ic_fold_count:
        raise ValueError(
            f"OOS diagnostic fold IC count mismatch for {report.signal_name} {window.window}"
        )

    insufficiency: list[str] = []
    if report.status != "ready":
        insufficiency.append("source diagnostics are not stability-ready")
    if not window.stability_ready:
        insufficiency.append("window is not stability-ready")
    if len(fold_ics) < config.min_ic_folds:
        insufficiency.append(
            f"IC folds {len(fold_ics)} < statistical gate minimum {config.min_ic_folds}"
        )
    if window.quantile_monotonicity_mean is None:
        insufficiency.append("quantile monotonicity is unavailable")
    if window.long_short_mean is None or window.positive_long_short_share is None:
        insufficiency.append("long-short stability is unavailable")

    p_value: float | None = None
    inference_method: str | None = None
    if len(fold_ics) >= config.min_ic_folds:
        p_value, inference_method = _one_sided_sign_flip_p_value(fold_ics)

    return _HypothesisEvidence(
        hypothesis_id=hypothesis_id,
        source_diagnostics_key=report.diagnostics_key,
        source_experiment_key=report.source_experiment_key,
        signal_name=report.signal_name,
        outcome_name=report.outcome_name,
        window=window.window,
        ic_fold_count=len(fold_ics),
        ic_mean=window.ic_mean,
        icir=window.icir,
        positive_ic_share=window.positive_ic_share,
        quantile_monotonicity_mean=window.quantile_monotonicity_mean,
        long_short_mean=window.long_short_mean,
        positive_long_short_share=window.positive_long_short_share,
        raw_p_value=p_value,
        inference_method=inference_method,
        insufficiency_reasons=insufficiency,
    )


def _decision(
    evidence: _HypothesisEvidence,
    adjusted_q_value: float | None,
    config: OOSSelectionConfig,
) -> OOSHypothesisDecision:
    reasons = list(evidence.insufficiency_reasons)
    if adjusted_q_value is None and not reasons:
        reasons.append("multiple-testing-adjusted q-value is unavailable")
    if reasons:
        status: OOSSelectionStatus = "insufficient"
    else:
        failures: list[str] = []
        if adjusted_q_value is not None and adjusted_q_value > config.max_fdr_q_value:
            failures.append(
                f"FDR q-value {adjusted_q_value:.4f} > maximum {config.max_fdr_q_value:.4f}"
            )
        if evidence.ic_mean is None or evidence.ic_mean < config.min_ic_mean:
            failures.append("mean OOS IC below predeclared minimum")
        if evidence.icir is None or evidence.icir < config.min_icir:
            failures.append("OOS ICIR below predeclared minimum")
        if (
            evidence.positive_ic_share is None
            or evidence.positive_ic_share < config.min_positive_ic_share
        ):
            failures.append("positive-IC fold share below predeclared minimum")
        if (
            evidence.quantile_monotonicity_mean is None
            or evidence.quantile_monotonicity_mean < config.min_quantile_monotonicity
        ):
            failures.append("OOS quantile monotonicity below predeclared minimum")
        if (
            evidence.long_short_mean is None
            or evidence.long_short_mean <= config.min_long_short_mean
        ):
            failures.append("mean OOS long-short spread is not positive enough")
        if (
            evidence.positive_long_short_share is None
            or evidence.positive_long_short_share < config.min_positive_long_short_share
        ):
            failures.append("positive long-short fold share below predeclared minimum")
        status = "rejected" if failures else "passes_statistical_gate"
        reasons.extend(failures)

    return OOSHypothesisDecision(
        hypothesis_id=evidence.hypothesis_id,
        source_diagnostics_key=evidence.source_diagnostics_key,
        source_experiment_key=evidence.source_experiment_key,
        signal_name=evidence.signal_name,
        outcome_name=evidence.outcome_name,
        window=evidence.window,
        status=status,
        reasons=reasons,
        ic_fold_count=evidence.ic_fold_count,
        ic_mean=evidence.ic_mean,
        icir=evidence.icir,
        positive_ic_share=evidence.positive_ic_share,
        quantile_monotonicity_mean=evidence.quantile_monotonicity_mean,
        long_short_mean=evidence.long_short_mean,
        positive_long_short_share=evidence.positive_long_short_share,
        raw_p_value=evidence.raw_p_value,
        adjusted_q_value=adjusted_q_value,
        inference_method=evidence.inference_method,
    )


def _one_sided_sign_flip_p_value(values: list[float]) -> tuple[float, str]:
    """Test whether the mean fold IC is positive under a symmetric zero-null."""
    if not values:
        raise ValueError("sign-flip inference requires at least one fold IC")
    observed_sum = sum(values)
    if len(values) <= _MAX_EXACT_SIGN_FLIP_FOLDS:
        total = 1 << len(values)
        extreme = 0
        for mask in range(total):
            signed_sum = sum(
                value if mask & (1 << index) else -value
                for index, value in enumerate(values)
            )
            if signed_sum >= observed_sum - 1e-15:
                extreme += 1
        return extreme / total, "exact_one_sided_fold_ic_sign_flip"

    variance = sum(value * value for value in values)
    if variance == 0:
        return 1.0, "normal_approximation_fold_ic_sign_flip"
    z_score = observed_sum / sqrt(variance)
    return 0.5 * erfc(z_score / sqrt(2.0)), "normal_approximation_fold_ic_sign_flip"


def _benjamini_hochberg(
    p_values: dict[str, float],
    *,
    family_size: int,
) -> dict[str, float]:
    if family_size < len(p_values):
        raise ValueError("multiple-testing family cannot be smaller than tested hypotheses")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank, (hypothesis_id, p_value) in reversed(list(enumerate(ordered, start=1))):
        running = min(running, p_value * family_size / rank)
        adjusted[hypothesis_id] = min(1.0, running)
    return adjusted


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
