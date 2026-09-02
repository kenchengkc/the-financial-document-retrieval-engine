from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fdre.research.oos_implementation import (
    OOSImplementationConfig,
    evaluate_oos_implementation,
)
from fdre.research.oos_selection import (
    OOSHypothesisDecision,
    OOSSelectionStatus,
    OOSSelectionSuiteReport,
)
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport


def _observation(
    ticker: str,
    feature: float,
    outcome: float,
    *,
    month: int,
    fold_id: str,
) -> WalkForwardOOSObservation:
    available = datetime(2024, month, 10, 20, tzinfo=UTC)
    return WalkForwardOOSObservation(
        ticker=ticker,
        accession_number=f"{ticker}-{month}",
        event_session=date(2024, month, 11),
        window="1:21",
        window_end_session=date(2024, month, 28),
        feature_value=feature,
        outcome_value=outcome,
        available_at=available,
        max_source_available_at=available,
        feature_lineage_id=f"lineage-{ticker}-{month}",
        fold_id=fold_id,
    )


def _source() -> WalkForwardStudyReport:
    observations: list[WalkForwardOOSObservation] = []
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    outcomes = [-0.02, -0.01, 0.01, 0.02]
    for month, fold_id in [(1, "fold-1"), (2, "fold-2")]:
        observations.extend(
            _observation(
                ticker,
                float(index),
                outcomes[index - 1],
                month=month,
                fold_id=fold_id,
            )
            for index, ticker in enumerate(tickers, start=1)
        )
    return WalkForwardStudyReport.model_construct(
        experiment_key="walk-forward-1",
        signal_name="risk_churn_rate",
        sealed_oos=True,
        oos_observations=observations,
    )


def _decision(
    status: OOSSelectionStatus = "passes_statistical_gate",
) -> OOSHypothesisDecision:
    return OOSHypothesisDecision(
        hypothesis_id="hypothesis-1",
        source_diagnostics_key="diagnostics-1",
        source_experiment_key="walk-forward-1",
        signal_name="risk_churn_rate",
        outcome_name="abnormal_return",
        window="1:21",
        status=status,
        reasons=[],
        ic_fold_count=4,
        ic_mean=0.04,
        icir=0.8,
        positive_ic_share=0.75,
        quantile_monotonicity_mean=0.8,
        long_short_mean=0.03,
        positive_long_short_share=0.75,
        raw_p_value=0.03,
        adjusted_q_value=0.06,
        inference_method="exact_one_sided_fold_ic_sign_flip",
    )


def _selection(
    status: OOSSelectionStatus = "passes_statistical_gate",
) -> OOSSelectionSuiteReport:
    return OOSSelectionSuiteReport.model_construct(
        selection_key="selection-1",
        decisions=[_decision(status)],
    )


def _config(**updates: object) -> OOSImplementationConfig:
    values: dict[str, object] = {
        "n_quantiles": 2,
        "min_rebalance_issuers": 4,
        "min_rebalances": 2,
        "max_annualized_turnover": 10.0,
    }
    values.update(updates)
    return OOSImplementationConfig.model_validate(values)


def test_implementation_reports_weight_turnover_and_cost_scenarios() -> None:
    report = evaluate_oos_implementation(_source(), _selection(), _config())

    result = report.windows[0]
    assert result.status == "passes_implementation_gate"
    assert result.rebalance_count == 2
    assert result.fold_count == 2
    assert result.mean_gross_return == pytest.approx(0.03)
    assert result.mean_turnover == pytest.approx(0.5)
    assert result.annualized_turnover == pytest.approx(6.0)
    assert [item.turnover for item in result.rebalances] == pytest.approx([1.0, 0.0])

    cost_25 = next(item for item in result.cost_scenarios if item.cost_bps == 25.0)
    assert cost_25.mean_net_return == pytest.approx(0.02875)
    assert cost_25.positive_fold_share == pytest.approx(1.0)
    assert result.capacity_status == "not_modeled"
    assert report.deployment_ready is False
    assert report.next_required_gate == "robustness_and_final_promotion"


def test_implementation_cannot_override_failed_statistical_gate() -> None:
    report = evaluate_oos_implementation(
        _source(),
        _selection("rejected"),
        _config(),
    )

    result = report.windows[0]
    assert result.status == "not_statistically_eligible"
    assert result.rebalances == []
    assert result.cost_scenarios == []


def test_execution_delay_must_be_supported_by_sealed_outcome_window() -> None:
    report = evaluate_oos_implementation(
        _source(),
        _selection(),
        _config(execution_delay_sessions=2),
    )

    result = report.windows[0]
    assert result.status == "insufficient"
    assert "begins before" in result.reasons[0]


def test_implementation_identity_changes_with_predeclared_cost_assumptions() -> None:
    first = evaluate_oos_implementation(_source(), _selection(), _config())
    second = evaluate_oos_implementation(
        _source(),
        _selection(),
        _config(cost_bps=[5.0, 10.0, 25.0, 75.0]),
    )

    assert first.implementation_key != second.implementation_key
