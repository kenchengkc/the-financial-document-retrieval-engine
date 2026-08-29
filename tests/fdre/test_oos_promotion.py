from __future__ import annotations

from datetime import UTC, date, datetime

from fdre.research.oos_diagnostics import OOSDiagnosticsReport, OOSWindowDiagnostic
from fdre.research.oos_implementation import (
    OOSCostScenarioResult,
    OOSImplementationRebalance,
    OOSImplementationReport,
    OOSImplementationWindowResult,
)
from fdre.research.oos_promotion import OOSPromotionConfig, evaluate_oos_promotion
from fdre.research.oos_selection import OOSHypothesisDecision, OOSSelectionSuiteReport
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport


def _observation(
    ticker: str,
    feature: float,
    outcome: float,
    *,
    fold_id: str,
    month: int,
) -> WalkForwardOOSObservation:
    available = datetime(2024, month, 10, 20, tzinfo=UTC)
    return WalkForwardOOSObservation(
        ticker=ticker,
        accession_number=f"{ticker}-{fold_id}",
        event_session=date(2024, month, 11),
        window="1:21",
        window_end_session=date(2024, month, 28),
        feature_value=feature,
        outcome_value=outcome,
        available_at=available,
        max_source_available_at=available,
        feature_lineage_id=f"lineage-{ticker}-{fold_id}",
        fold_id=fold_id,
    )


def _source(*, reverse_second_slice: bool = False) -> WalkForwardStudyReport:
    observations: list[WalkForwardOOSObservation] = []
    for fold_index, fold_id in enumerate(["fold-1", "fold-2"], start=1):
        for index, ticker in enumerate(["AAA", "BBB", "CCC", "DDD"], start=1):
            observations.append(
                _observation(
                    ticker,
                    float(index),
                    float(index) / 100,
                    fold_id=fold_id,
                    month=fold_index,
                )
            )
        for index, ticker in enumerate(["EEE", "FFF", "GGG", "HHH"], start=1):
            outcome = float(5 - index if reverse_second_slice else index) / 100
            observations.append(
                _observation(
                    ticker,
                    float(index),
                    outcome,
                    fold_id=fold_id,
                    month=fold_index,
                )
            )
    return WalkForwardStudyReport.model_construct(
        experiment_key="walk-forward-1",
        signal_name="risk_churn_rate",
        outcome_name="abnormal_return",
        sealed_oos=True,
        oos_observations=observations,
    )


def _diagnostics() -> OOSDiagnosticsReport:
    return OOSDiagnosticsReport.model_construct(
        diagnostics_key="diagnostics-1",
        source_experiment_key="walk-forward-1",
        signal_name="risk_churn_rate",
        outcome_name="abnormal_return",
        sealed_oos=True,
        windows=[
            OOSWindowDiagnostic.model_construct(window="1:21", ic_mean=0.45),
            OOSWindowDiagnostic.model_construct(window="1:61", ic_mean=0.20),
        ],
    )


def _selection(status: str = "passes_statistical_gate") -> OOSSelectionSuiteReport:
    return OOSSelectionSuiteReport.model_construct(
        selection_key="selection-1",
        decisions=[
            OOSHypothesisDecision.model_construct(
                hypothesis_id="hypothesis-1",
                source_experiment_key="walk-forward-1",
                signal_name="risk_churn_rate",
                outcome_name="abnormal_return",
                window="1:21",
                status=status,
            )
        ],
    )


def _implementation(status: str = "passes_implementation_gate") -> OOSImplementationReport:
    rebalances = [
        OOSImplementationRebalance(
            fold_id="fold-1",
            period="2024-01",
            window="1:21",
            issuer_count=8,
            long_tickers=["CCC", "DDD"],
            short_tickers=["AAA", "BBB"],
            gross_return=0.03,
            turnover=1.0,
            net_returns={"50bps": 0.025},
        ),
        OOSImplementationRebalance(
            fold_id="fold-2",
            period="2024-02",
            window="1:21",
            issuer_count=8,
            long_tickers=["CCC", "DDD"],
            short_tickers=["AAA", "BBB"],
            gross_return=0.03,
            turnover=0.0,
            net_returns={"50bps": 0.03},
        ),
    ]
    result = OOSImplementationWindowResult.model_construct(
        hypothesis_id="hypothesis-1",
        signal_name="risk_churn_rate",
        window="1:21",
        status=status,
        cost_scenarios=[
            OOSCostScenarioResult(
                cost_bps=50.0,
                mean_net_return=0.0275,
                positive_rebalance_share=1.0,
                positive_fold_share=1.0,
            )
        ],
        rebalances=rebalances,
    )
    return OOSImplementationReport.model_construct(
        implementation_key="implementation-1",
        source_experiment_key="walk-forward-1",
        source_selection_key="selection-1",
        signal_name="risk_churn_rate",
        sealed_oos=True,
        windows=[result],
    )


def _slices() -> dict[str, set[str]]:
    return {
        "sector:first": {"AAA", "BBB", "CCC", "DDD"},
        "sector:second": {"EEE", "FFF", "GGG", "HHH"},
    }


def _config() -> OOSPromotionConfig:
    return OOSPromotionConfig(
        min_slice_observations_per_fold=4,
        min_slice_folds=2,
        min_analyzable_slices=2,
        min_decay_horizons=2,
        max_single_name_weight=0.50,
    )


def test_final_gate_promotes_only_after_all_robustness_checks_pass() -> None:
    report = evaluate_oos_promotion(
        _source(),
        _diagnostics(),
        _selection(),
        _implementation(),
        slices=_slices(),
        config=_config(),
    )

    decision = report.decisions[0]
    assert decision.status == "promote"
    assert decision.positive_slice_share == 1.0
    assert decision.positive_horizon_share == 1.0
    assert decision.stress_net_mean == 0.0275
    assert decision.max_single_name_weight == 0.5
    assert decision.live_trading_ready is False


def test_negative_predeclared_slice_rejects_candidate() -> None:
    report = evaluate_oos_promotion(
        _source(reverse_second_slice=True),
        _diagnostics(),
        _selection(),
        _implementation(),
        slices=_slices(),
        config=_config(),
    )

    decision = report.decisions[0]
    assert decision.status == "reject"
    assert decision.positive_slice_share == 0.5
    assert any("robustness-slice" in reason for reason in decision.reasons)


def test_missing_required_slice_breadth_is_insufficient_not_promoted() -> None:
    report = evaluate_oos_promotion(
        _source(),
        _diagnostics(),
        _selection(),
        _implementation(),
        slices={"tiny": {"AAA"}},
        config=_config(),
    )

    decision = report.decisions[0]
    assert decision.status == "insufficient"
    assert any("analyzable robustness slices" in reason for reason in decision.reasons)


def test_upstream_rejection_cannot_be_promoted() -> None:
    report = evaluate_oos_promotion(
        _source(),
        _diagnostics(),
        _selection("rejected"),
        _implementation(),
        slices=_slices(),
        config=_config(),
    )

    assert report.decisions[0].status == "reject"


def test_promotion_identity_changes_when_slice_membership_changes() -> None:
    first = evaluate_oos_promotion(
        _source(),
        _diagnostics(),
        _selection(),
        _implementation(),
        slices=_slices(),
        config=_config(),
    )
    changed = _slices()
    changed["sector:first"] = {"AAA", "BBB", "CCC"}
    second = evaluate_oos_promotion(
        _source(),
        _diagnostics(),
        _selection(),
        _implementation(),
        slices=changed,
        config=_config(),
    )

    assert first.slice_snapshot_id != second.slice_snapshot_id
    assert first.promotion_key != second.promotion_key
