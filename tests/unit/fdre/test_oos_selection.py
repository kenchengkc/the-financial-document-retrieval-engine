from __future__ import annotations

from statistics import mean, stdev

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models import ResearchExperiment
from fdre.research.oos_diagnostics import (
    OOSDiagnosticsConfig,
    OOSDiagnosticsReport,
    OOSFoldWindowDiagnostic,
    OOSWindowDiagnostic,
)
from fdre.research.oos_selection import (
    OOSSelectionConfig,
    _one_sided_sign_flip_p_value,
    evaluate_oos_selection_suite,
    persist_oos_selection_suite,
)


def _diagnostics(
    signal_name: str,
    ic_values: list[float],
    *,
    window: str = "1:21",
    diagnostics_key: str | None = None,
    monotonicity: float | None = 0.8,
    long_short_values: list[float] | None = None,
    stability_ready: bool = True,
) -> OOSDiagnosticsReport:
    spreads = long_short_values or [0.01 + index * 0.001 for index in range(len(ic_values))]
    assert len(spreads) == len(ic_values)
    folds = [
        OOSFoldWindowDiagnostic(
            fold_id=f"fold-{index + 1}",
            window=window,
            status="ready",
            sample_size=50,
            issuer_count=40,
            information_coefficient=ic,
            quantiles=[],
            quantile_monotonicity=monotonicity,
            long_short_mean=spread,
        )
        for index, (ic, spread) in enumerate(zip(ic_values, spreads, strict=True))
    ]
    ic_std = stdev(ic_values) if len(ic_values) >= 2 else None
    ic_mean = mean(ic_values) if ic_values else None
    window_result = OOSWindowDiagnostic(
        window=window,
        observed_fold_count=len(folds),
        analyzable_fold_count=len(folds),
        observation_count=len(folds) * 50,
        issuer_count=100,
        minimum_fold_sample_size=50,
        minimum_fold_issuer_count=40,
        ic_fold_count=len(ic_values),
        ic_mean=ic_mean,
        ic_std=ic_std,
        icir=(ic_mean / ic_std if ic_mean is not None and ic_std not in (None, 0) else None),
        positive_ic_share=(
            sum(value > 0 for value in ic_values) / len(ic_values) if ic_values else None
        ),
        quantile_monotonicity_fold_count=len(folds) if monotonicity is not None else 0,
        quantile_monotonicity_mean=monotonicity,
        long_short_fold_count=len(spreads),
        long_short_mean=mean(spreads) if spreads else None,
        positive_long_short_share=(
            sum(value > 0 for value in spreads) / len(spreads) if spreads else None
        ),
        stability_ready=stability_ready,
    )
    return OOSDiagnosticsReport(
        diagnostics_key=diagnostics_key or f"diag-{signal_name}-{window}",
        source_experiment_key=f"source-{signal_name}",
        signal_name=signal_name,
        outcome_name="abnormal_return",
        status="ready" if stability_ready else "insufficient_oos_data",
        dataset_version="dataset-v1",
        feature_version=f"feature-{signal_name}",
        market_data_version="market-v1",
        universe_snapshot_id="universe-v1",
        feature_snapshot_id=f"snapshot-{signal_name}",
        code_sha="a" * 40,
        source_eligible_fold_count=len(folds),
        source_oos_event_count=len(folds) * 50,
        source_oos_observation_count=len(folds) * 50,
        config=OOSDiagnosticsConfig(),
        windows=[window_result],
        folds=folds,
    )


def test_exact_sign_flip_inference_for_all_positive_fold_ics() -> None:
    p_value, method = _one_sided_sign_flip_p_value([0.03, 0.04, 0.05, 0.06, 0.07])

    assert p_value == pytest.approx(1 / 32)
    assert method == "exact_one_sided_fold_ic_sign_flip"


def test_strong_oos_hypothesis_passes_statistical_gate() -> None:
    report = evaluate_oos_selection_suite(
        [_diagnostics("quality", [0.04, 0.05, 0.06, 0.05, 0.07])]
    )

    assert report.deployment_ready is False
    assert report.next_required_gate == "turnover_and_transaction_costs"
    assert report.declared_hypothesis_count == 1
    assert report.tested_hypothesis_count == 1
    assert report.passing_count == 1
    decision = report.decisions[0]
    assert decision.status == "passes_statistical_gate"
    assert decision.raw_p_value == pytest.approx(1 / 32)
    assert decision.adjusted_q_value == pytest.approx(1 / 32)
    assert decision.reasons == []


def test_bh_counts_full_predeclared_family_and_can_reject_nominal_signal() -> None:
    strong = _diagnostics("quality", [0.04, 0.05, 0.06, 0.05, 0.07])
    insufficient = [
        _diagnostics(
            f"missing-{index}",
            [0.04, 0.05, 0.06],
            stability_ready=False,
        )
        for index in range(3)
    ]

    report = evaluate_oos_selection_suite([strong, *insufficient])
    strong_decision = next(item for item in report.decisions if item.signal_name == "quality")

    assert report.declared_hypothesis_count == 4
    assert report.tested_hypothesis_count == 1
    assert strong_decision.raw_p_value == pytest.approx(1 / 32)
    assert strong_decision.adjusted_q_value == pytest.approx(4 / 32)
    assert strong_decision.status == "rejected"
    assert any("FDR q-value" in reason for reason in strong_decision.reasons)
    assert report.insufficient_count == 3


def test_negative_well_powered_signal_is_rejected_not_insufficient() -> None:
    report = evaluate_oos_selection_suite(
        [_diagnostics("bad", [-0.04, -0.05, -0.06, -0.05, -0.07])]
    )

    decision = report.decisions[0]
    assert decision.status == "rejected"
    assert decision.raw_p_value is not None
    assert any("mean OOS IC" in reason for reason in decision.reasons)
    assert any("positive-IC" in reason for reason in decision.reasons)


def test_too_few_folds_is_explicitly_insufficient() -> None:
    report = evaluate_oos_selection_suite(
        [_diagnostics("young", [0.08, 0.09, 0.10], stability_ready=True)]
    )

    decision = report.decisions[0]
    assert decision.status == "insufficient"
    assert decision.raw_p_value is None
    assert decision.adjusted_q_value is None
    assert any("IC folds 3" in reason for reason in decision.reasons)


def test_suite_identity_and_decisions_are_order_invariant() -> None:
    left = _diagnostics("left", [0.04, 0.05, 0.06, 0.05, 0.07])
    right = _diagnostics("right", [0.03, 0.04, 0.05, 0.04, 0.06])

    first = evaluate_oos_selection_suite([left, right])
    second = evaluate_oos_selection_suite([right, left])

    assert first.selection_key == second.selection_key
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_duplicate_predeclared_hypothesis_fails_closed() -> None:
    first = _diagnostics(
        "quality",
        [0.04, 0.05, 0.06, 0.05, 0.07],
        diagnostics_key="diag-a",
    )
    duplicate = _diagnostics(
        "quality",
        [0.03, 0.04, 0.05, 0.04, 0.06],
        diagnostics_key="diag-b",
    )

    with pytest.raises(ValueError, match="duplicate OOS hypothesis"):
        evaluate_oos_selection_suite([first, duplicate])


def test_selection_thresholds_are_part_of_experiment_identity() -> None:
    diagnostics = [_diagnostics("quality", [0.04, 0.05, 0.06, 0.05, 0.07])]
    first = evaluate_oos_selection_suite(diagnostics)
    second = evaluate_oos_selection_suite(
        diagnostics,
        OOSSelectionConfig(min_ic_mean=0.03),
    )

    assert first.selection_key != second.selection_key


def test_persist_selection_suite_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    report = evaluate_oos_selection_suite(
        [_diagnostics("quality", [0.04, 0.05, 0.06, 0.05, 0.07])]
    )

    with Session(engine) as session:
        first = persist_oos_selection_suite(session, report)
        second = persist_oos_selection_suite(session, report)
        rows = list(
            session.scalars(
                select(ResearchExperiment).where(
                    ResearchExperiment.experiment_type == "oos_signal_selection_suite"
                )
            )
        )

    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].experiment_key == report.selection_key
    assert rows[0].results_json["deployment_ready"] is False
