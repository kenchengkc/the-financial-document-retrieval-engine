from types import SimpleNamespace

from scripts.retrieval_pipeline import _signal_feature_value, _signal_panel_features


def test_filing_lateness_is_a_standalone_panel_signal() -> None:
    row = SimpleNamespace(filing_delay_days=47)

    assert _signal_panel_features("filing_lateness") == ["filing_timing"]
    assert _signal_feature_value(row, "filing_lateness") == 47.0


def test_filing_lateness_rejects_missing_delay() -> None:
    row = SimpleNamespace(filing_delay_days=None)

    assert _signal_feature_value(row, "filing_lateness") is None
