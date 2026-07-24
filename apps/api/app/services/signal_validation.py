from __future__ import annotations

from copy import deepcopy
from math import sqrt
from typing import Any

from fdre.research.signal_specs import get_signal_spec


def enrich_signal_study_payloads(
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched = deepcopy(payloads)
    hypotheses: list[tuple[int, int, float]] = []
    for study_index, payload in enumerate(enriched):
        report = payload.get("report") or {}
        for result_index, result in enumerate(report.get("results") or []):
            raw_p = result.get("long_short_p_value")
            if isinstance(raw_p, (int, float)):
                hypotheses.append((study_index, result_index, float(raw_p)))

    adjusted = _benjamini_hochberg([item[2] for item in hypotheses])
    for (study_index, result_index, _), value in zip(
        hypotheses, adjusted, strict=True
    ):
        result = enriched[study_index]["report"]["results"][result_index]
        result["suite_adjusted_p_value"] = value

    hypothesis_count = len(hypotheses)
    for payload in enriched:
        _enrich_report(payload.get("report") or {}, hypothesis_count)
    return enriched


def _enrich_report(report: dict[str, Any], hypothesis_count: int) -> None:
    signal_name = str(report.get("signal_name", ""))
    try:
        spec = get_signal_spec(signal_name)
    except ValueError:
        spec = None
    if spec is not None and not report.get("definition"):
        report["definition"] = spec.as_dict()

    results = report.get("results") or []
    for result in results:
        quantiles = result.get("quantiles") or []
        points = [
            (float(item["quantile"]), float(item["mean_abnormal_return"]))
            for item in quantiles
            if item.get("mean_abnormal_return") is not None
        ]
        result["quantile_monotonicity"] = (
            _spearman(
                [point[0] for point in points],
                [point[1] for point in points],
            )
            if len(points) >= 3
            else None
        )

    preferred = set(spec.default_windows if spec is not None else ())
    preferred_results = [
        result for result in results if not preferred or result.get("window") in preferred
    ]
    usable = [
        result
        for result in preferred_results
        if result.get("information_coefficient") is not None
        and result.get("long_short_mean") is not None
    ]
    best = max(
        usable,
        key=lambda result: (
            _number(result.get("information_coefficient"), 0.0),
            _number(result.get("quantile_monotonicity"), -1.0),
            -_number(result.get("suite_adjusted_p_value"), 1.0),
        ),
        default=None,
    )
    horizon_stability = (
        sum(float(result.get("long_short_mean") or 0.0) > 0 for result in usable)
        / len(usable)
        if usable
        else 0.0
    )
    best_window = str(best.get("window")) if best is not None else None
    minimum_period_sample = max(10 * int(report.get("n_quantiles") or 5), 50)
    period_results = [
        period
        for period in report.get("period_results") or []
        if best_window is not None
        and str(period.get("window")) == best_window
        and int(period.get("sample_size") or 0) >= minimum_period_sample
        and period.get("information_coefficient") is not None
        and period.get("long_short_mean") is not None
    ]
    direction_stability = (
        sum(
            _number(period.get("information_coefficient"), 0.0) > 0
            and _number(period.get("long_short_mean"), 0.0) > 0
            for period in period_results
        )
        / len(period_results)
        if len(period_results) >= 2
        else horizon_stability
    )
    peak_abs_ic = max(
        (abs(float(result.get("information_coefficient") or 0.0)) for result in usable),
        default=0.0,
    )
    best_p = (
        min(_number(result.get("suite_adjusted_p_value"), 1.0) for result in usable)
        if usable
        else None
    )
    outcome_aligned = (
        spec is None
        or str(report.get("outcome_name", "abnormal_return")) == spec.default_outcome
    )
    tested_windows = {str(result.get("window")) for result in results}
    horizon_aligned = not preferred or bool(preferred & tested_windows)
    status, reason = _research_status(
        best,
        direction_stability=direction_stability,
        periods_tested=len(period_results),
        outcome_aligned=outcome_aligned,
        horizon_aligned=horizon_aligned,
    )
    report["quality"] = {
        "status": status,
        "reason": reason,
        "multiple_testing_method": "Benjamini-Hochberg across published signal-horizon tests",
        "suite_hypotheses": hypothesis_count,
        "best_suite_adjusted_p_value": best_p,
        "peak_absolute_ic": peak_abs_ic,
        "direction_stability": direction_stability,
        "stability_basis": (
            "annual_periods" if len(period_results) >= 2 else "tested_horizons"
        ),
        "periods_tested": len(period_results),
        "period_sample_minimum": minimum_period_sample,
        "best_window": best_window,
        "best_quantile_monotonicity": (
            best.get("quantile_monotonicity") if best is not None else None
        ),
        "outcome_aligned": outcome_aligned,
        "horizon_aligned": horizon_aligned,
        "preferred_windows": list(spec.default_windows) if spec is not None else [],
    }


def _research_status(
    best: dict[str, Any] | None,
    *,
    direction_stability: float,
    periods_tested: int,
    outcome_aligned: bool,
    horizon_aligned: bool,
) -> tuple[str, str]:
    if best is None:
        return "Exploratory", "No horizon has enough observations for inference."
    sample_size = int(best.get("sample_size") or 0)
    information_coefficient = float(best.get("information_coefficient") or 0.0)
    monotonicity = float(best.get("quantile_monotonicity") or 0.0)
    suite_p = _number(best.get("suite_adjusted_p_value"), 1.0)
    aligned = outcome_aligned and horizon_aligned
    if (
        aligned
        and sample_size >= 250
        and information_coefficient >= 0.02
        and monotonicity >= 0.6 - 1e-9
        and periods_tested >= 3
        and direction_stability >= 2 / 3
        and suite_p < 0.05
    ):
        return (
            "Validated",
            "Positive, monotonic evidence is stable by year and survives suite-wide testing.",
        )
    if (
        aligned
        and sample_size >= 200
        and information_coefficient >= 0.03
        and monotonicity >= 0.6 - 1e-9
        and periods_tested >= 2
        and direction_stability >= 0.5
    ):
        return (
            "Promising",
            "Economically aligned rank evidence is positive across multiple years.",
        )
    if not aligned:
        return "Exploratory", "The published outcome or horizons do not match the signal thesis."
    return "Exploratory", "Evidence is weak, unstable, or non-monotonic."


def _number(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running = 1.0
    total = len(ordered)
    for rank, (index, value) in reversed(list(enumerate(ordered, start=1))):
        running = min(running, value * total / rank)
        adjusted[index] = min(1.0, running)
    return [adjusted[index] for index in range(len(p_values))]


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    left_mean = sum(left_ranks) / len(left_ranks)
    right_mean = sum(right_ranks) / len(right_ranks)
    numerator = sum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left_ranks, right_ranks, strict=True)
    )
    left_scale = sqrt(sum((value - left_mean) ** 2 for value in left_ranks))
    right_scale = sqrt(sum((value - right_mean) ** 2 for value in right_ranks))
    denominator = left_scale * right_scale
    return numerator / denominator if denominator else None


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index, _ in ordered[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks
