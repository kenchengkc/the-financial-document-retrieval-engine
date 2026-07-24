from __future__ import annotations

import pytest

from apps.api.app.services.signal_validation import enrich_signal_study_payloads


def test_signal_validation_applies_suite_wide_bh_and_quality_gates() -> None:
    studies = [
        _study(
            "disclosure_similarity",
            [
                _window("0:1", raw_p=0.01, ic=0.05, means=[-0.02, -0.01, 0, 0.01, 0.02]),
                _window("1:21", raw_p=0.04, ic=0.04, means=[-0.01, 0, 0.01, 0.02, 0.03]),
            ],
            periods=[
                _period("2023", "0:1", 120, 0.03, 0.02),
                _period("2024", "0:1", 130, 0.04, 0.03),
                _period("2025", "0:1", 150, 0.05, 0.04),
            ],
        ),
        _study(
            "asset_growth",
            [
                _window("1:63", raw_p=0.20, ic=-0.04, means=[0.03, 0.02, 0.01, 0, -0.01]),
                _window("1:126", raw_p=0.60, ic=-0.01, means=[0.01, 0, 0.01, 0, -0.01]),
            ],
        ),
    ]

    enriched = enrich_signal_study_payloads(studies)

    first = enriched[0]["report"]
    assert first["results"][0]["suite_adjusted_p_value"] == pytest.approx(0.04)
    assert first["results"][0]["quantile_monotonicity"] == pytest.approx(1.0)
    assert first["quality"]["suite_hypotheses"] == 4
    assert first["quality"]["status"] == "Validated"
    assert first["quality"]["stability_basis"] == "annual_periods"
    assert first["quality"]["periods_tested"] == 3
    assert first["quality"]["period_sample_minimum"] == 50
    assert first["definition"]["family"] == "Language"

    second = enriched[1]["report"]
    assert second["results"][0]["suite_adjusted_p_value"] == pytest.approx(0.2666667)
    assert second["quality"]["status"] == "Exploratory"


def _study(
    signal_name: str,
    results: list[dict[str, object]],
    *,
    periods: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "experiment_id": 1,
        "report": {
            "signal_name": signal_name,
            "outcome_name": "abnormal_return",
            "event_count": 400,
            "results": results,
            "period_results": periods or [],
        },
    }


def _period(
    period: str,
    window: str,
    sample_size: int,
    information_coefficient: float,
    long_short_mean: float,
) -> dict[str, object]:
    return {
        "period": period,
        "window": window,
        "sample_size": sample_size,
        "information_coefficient": information_coefficient,
        "long_short_mean": long_short_mean,
    }


def _window(
    window: str,
    *,
    raw_p: float,
    ic: float,
    means: list[float],
) -> dict[str, object]:
    return {
        "window": window,
        "sample_size": 400,
        "information_coefficient": ic,
        "long_short_mean": means[-1] - means[0],
        "long_short_p_value": raw_p,
        "quantiles": [
            {
                "quantile": index,
                "sample_size": 80,
                "mean_abnormal_return": value,
            }
            for index, value in enumerate(means, start=1)
        ],
    }
