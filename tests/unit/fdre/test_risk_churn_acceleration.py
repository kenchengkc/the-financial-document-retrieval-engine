from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fdre.research.panel import FeatureLineage, PanelFeature, ResearchPanelRow
from fdre.research.risk_churn_acceleration import (
    RISK_CHURN_ACCELERATION_VERSION,
    build_risk_churn_acceleration_events,
)


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 20, tzinfo=UTC)


def _risk_lineage(
    sources: list[str],
    times: dict[str, datetime],
    *,
    snapshot: str = "snapshot-1",
) -> FeatureLineage:
    return FeatureLineage(
        feature="risk_changes",
        calculation_version="risk-changes-v1",
        parameters={},
        source_accessions=sources,
        source_available_at=times,
        max_source_available_at=max(times.values()),
        corpus_snapshot_id=snapshot,
        lineage_id="a" * 64,
    )


def _row(
    accession: str,
    available_at: datetime,
    churn: float,
    lineage: FeatureLineage | None,
) -> ResearchPanelRow:
    feature_lineage: dict[PanelFeature, FeatureLineage] = (
        {"risk_changes": lineage} if lineage is not None else {}
    )
    return ResearchPanelRow(
        ticker="AAA",
        cik="0000000001",
        accession_number=accession,
        form_type="10-K",
        period_end=date(available_at.year - 1, 12, 31),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=False,
        risk_churn_rate=churn,
        source_accessions=list(lineage.source_accessions) if lineage else [accession],
        feature_provenance={},
        feature_lineage=feature_lineage,
        calculation_version="fdre-panel-v3",
        corpus_snapshot_id="snapshot-1",
        max_source_available_at=(
            lineage.max_source_available_at if lineage else available_at
        ),
    )


def test_acceleration_uses_selected_comparable_prior_not_chronological_neighbor() -> None:
    z_time = _at(2022, 3, 1)
    a_time = _at(2023, 3, 1)
    b_time = _at(2023, 9, 1)
    c_time = _at(2024, 3, 1)
    rows = [
        _row(
            "Z",
            z_time,
            0.10,
            _risk_lineage(["Z"], {"Z": z_time}),
        ),
        _row(
            "A",
            a_time,
            0.25,
            _risk_lineage(["A", "Z"], {"A": a_time, "Z": z_time}),
        ),
        _row(
            "B",
            b_time,
            0.90,
            _risk_lineage(["B", "Z"], {"B": b_time, "Z": z_time}),
        ),
        _row(
            "C",
            c_time,
            0.40,
            _risk_lineage(["C", "A"], {"C": c_time, "A": a_time}),
        ),
    ]

    events = build_risk_churn_acceleration_events(rows)
    current = next(event for event in events if event.accession_number == "C")

    assert current.feature_value == pytest.approx(-0.15)
    assert current.feature_lineage is not None
    assert current.feature_lineage.calculation_version == RISK_CHURN_ACCELERATION_VERSION
    assert current.feature_lineage.source_accessions == ["C", "A", "Z"]
    assert current.max_source_available_at == c_time


def test_acceleration_lineage_id_is_deterministic() -> None:
    z_time = _at(2022, 3, 1)
    a_time = _at(2023, 3, 1)
    c_time = _at(2024, 3, 1)
    rows = [
        _row("Z", z_time, 0.10, _risk_lineage(["Z"], {"Z": z_time})),
        _row(
            "A",
            a_time,
            0.25,
            _risk_lineage(["A", "Z"], {"A": a_time, "Z": z_time}),
        ),
        _row(
            "C",
            c_time,
            0.40,
            _risk_lineage(["C", "A"], {"C": c_time, "A": a_time}),
        ),
    ]

    first = build_risk_churn_acceleration_events(rows)
    second = build_risk_churn_acceleration_events(rows)
    first_c = next(event for event in first if event.accession_number == "C")
    second_c = next(event for event in second if event.accession_number == "C")

    assert first_c.feature_lineage is not None
    assert second_c.feature_lineage is not None
    assert first_c.feature_lineage.lineage_id == second_c.feature_lineage.lineage_id
    assert len(first_c.feature_lineage.lineage_id) == 64


def test_acceleration_rejects_conflicting_source_availability() -> None:
    z_time = _at(2022, 3, 1)
    a_time = _at(2023, 3, 1)
    c_time = _at(2024, 3, 1)
    rows = [
        _row(
            "A",
            a_time,
            0.25,
            _risk_lineage(
                ["A", "Z"],
                {"A": _at(2023, 3, 2), "Z": z_time},
            ),
        ),
        _row(
            "C",
            c_time,
            0.40,
            _risk_lineage(["C", "A"], {"C": c_time, "A": a_time}),
        ),
    ]

    with pytest.raises(ValueError, match="conflicting source availability"):
        build_risk_churn_acceleration_events(rows)


def test_acceleration_rejects_future_source_lineage() -> None:
    a_time = _at(2023, 3, 1)
    c_time = _at(2024, 3, 1)
    future = _at(2024, 4, 1)
    rows = [
        _row(
            "A",
            a_time,
            0.25,
            _risk_lineage(["A", "Z"], {"A": a_time, "Z": future}),
        ),
        _row(
            "C",
            c_time,
            0.40,
            _risk_lineage(["C", "A"], {"C": c_time, "A": a_time}),
        ),
    ]

    with pytest.raises(ValueError, match="acceleration leakage"):
        build_risk_churn_acceleration_events(rows)


def test_acceleration_skips_prior_without_its_own_churn_lineage() -> None:
    a_time = _at(2023, 3, 1)
    c_time = _at(2024, 3, 1)
    rows = [
        _row("A", a_time, 0.25, None),
        _row(
            "C",
            c_time,
            0.40,
            _risk_lineage(["C", "A"], {"C": c_time, "A": a_time}),
        ),
    ]

    assert build_risk_churn_acceleration_events(rows) == []
