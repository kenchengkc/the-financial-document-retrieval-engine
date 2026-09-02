from __future__ import annotations

from scripts.flagship_risk_churn_acceleration import _primary_result_status


def test_primary_status_reports_not_yet_realized_without_oos_observations() -> None:
    status, reason = _primary_result_status(0, None)

    assert status == "insufficient_not_yet_realized"
    assert "fully realized primary-horizon outcome" in reason


def test_primary_status_preserves_final_promotion_decision() -> None:
    status, reason = _primary_result_status(12, "reject")

    assert status == "reject"
    assert "final sealed-OOS promotion layer" in reason


def test_primary_status_flags_missing_decision_when_observations_exist() -> None:
    status, reason = _primary_result_status(12, None)

    assert status == "insufficient_no_promotion_decision"
    assert "no final promotion decision" in reason
