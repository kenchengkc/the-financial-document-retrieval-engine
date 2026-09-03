from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models import ResearchExperiment
from fdre.research.oos_diagnostics import (
    OOSDiagnosticsConfig,
    build_oos_diagnostics,
    persist_oos_diagnostics,
)
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport


def _observation(
    *,
    fold_id: str,
    index: int,
    outcome: float,
    window: str = "1:21",
) -> WalkForwardOOSObservation:
    available_at = datetime(2020 + int(fold_id[-1]), 1, 15, 21, tzinfo=UTC) + timedelta(
        days=index
    )
    return WalkForwardOOSObservation(
        fold_id=fold_id,
        ticker=f"T{fold_id[-1]}{index:02d}",
        accession_number=f"{fold_id}-{index:02d}",
        event_session=available_at.date(),
        window=window,
        window_end_session=available_at.date() + timedelta(days=21),
        feature_value=float(index + 1),
        outcome_value=outcome,
        available_at=available_at,
        max_source_available_at=available_at,
    )


def _source(
    observations: list[WalkForwardOOSObservation],
    *,
    experiment_key: str = "source-experiment",
    eligible_fold_count: int = 3,
) -> WalkForwardStudyReport:
    return WalkForwardStudyReport.model_construct(
        experiment_key=experiment_key,
        signal_name="synthetic_signal",
        outcome_name="abnormal_return",
        sealed_oos=True,
        dataset_version="dataset-v1",
        feature_version="feature-v1",
        market_data_version="market-v1",
        universe_snapshot_id="universe-v1",
        feature_snapshot_id="features-v1",
        code_sha="deadbeef",
        eligible_fold_count=eligible_fold_count,
        oos_event_count=len({item.accession_number for item in observations}),
        oos_observation_count=len(observations),
        oos_observations=observations,
    )


def _stable_sample() -> list[WalkForwardOOSObservation]:
    outcomes = {
        "fold-1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "fold-2": [1, 2, 3, 4, 5, 6, 7, 8, 10, 9],
        "fold-3": [1, 2, 3, 4, 5, 6, 8, 7, 10, 9],
    }
    return [
        _observation(fold_id=fold_id, index=index, outcome=float(outcome))
        for fold_id, fold_outcomes in outcomes.items()
        for index, outcome in enumerate(fold_outcomes)
    ]


def test_builds_fold_level_stability_metrics_from_sealed_oos_only() -> None:
    report = build_oos_diagnostics(_source(_stable_sample()))

    assert report.status == "ready"
    assert report.promotion_status == "not_evaluated"
    assert len(report.folds) == 3
    assert all(fold.status == "ready" for fold in report.folds)
    assert all(fold.information_coefficient is not None for fold in report.folds)
    assert all(fold.quantile_monotonicity is not None for fold in report.folds)
    assert all(fold.long_short_mean is not None for fold in report.folds)

    window = report.windows[0]
    assert window.window == "1:21"
    assert window.observed_fold_count == 3
    assert window.analyzable_fold_count == 3
    assert window.ic_fold_count == 3
    assert window.ic_mean is not None and window.ic_mean > 0
    assert window.ic_std is not None and window.ic_std > 0
    assert window.icir is not None and window.icir > 0
    assert window.positive_ic_share == 1.0
    assert window.positive_long_short_share == 1.0
    assert window.stability_ready


def test_fold_quantiles_are_formed_within_each_oos_fold() -> None:
    observations = _stable_sample()
    for observation in observations:
        if observation.fold_id == "fold-2":
            observation.feature_value *= 1_000

    report = build_oos_diagnostics(_source(observations))

    assert [len(fold.quantiles) for fold in report.folds] == [5, 5, 5]
    assert all(
        [item.sample_size for item in fold.quantiles] == [2, 2, 2, 2, 2]
        for fold in report.folds
    )


def test_suppresses_narrow_fold_metrics_without_dropping_oos_count() -> None:
    observations = [
        _observation(fold_id="fold-1", index=index, outcome=float(index))
        for index in range(4)
    ]
    report = build_oos_diagnostics(
        _source(observations, eligible_fold_count=1),
        OOSDiagnosticsConfig(min_stability_folds=2),
    )

    assert report.status == "insufficient_oos_data"
    assert report.source_oos_observation_count == 4
    assert report.folds[0].status == "insufficient_breadth"
    assert report.folds[0].information_coefficient is None
    assert report.folds[0].quantiles == []
    assert report.windows[0].analyzable_fold_count == 0
    assert report.windows[0].icir is None
    assert any("suppressed" in warning for warning in report.warnings)


def test_empty_sealed_oos_sample_reports_insufficient_data() -> None:
    report = build_oos_diagnostics(_source([], eligible_fold_count=0))

    assert report.status == "insufficient_oos_data"
    assert report.windows == []
    assert report.folds == []
    assert report.warnings == ["sealed OOS sample contains no observations"]


def test_diagnostics_are_deterministic_under_observation_reordering() -> None:
    observations = _stable_sample()
    first = build_oos_diagnostics(_source(observations))
    second = build_oos_diagnostics(_source(list(reversed(observations))))

    assert first.diagnostics_key == second.diagnostics_key
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_reporting_config_changes_diagnostics_identity() -> None:
    source = _source(_stable_sample())
    default = build_oos_diagnostics(source)
    alternate = build_oos_diagnostics(
        source,
        OOSDiagnosticsConfig(n_quantiles=2, min_stability_folds=2),
    )

    assert default.diagnostics_key != alternate.diagnostics_key


def test_persist_oos_diagnostics_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    report = build_oos_diagnostics(_source(_stable_sample()))

    with Session(engine) as session:
        first = persist_oos_diagnostics(session, report)
        second = persist_oos_diagnostics(session, report)
        experiments = list(
            session.scalars(
                select(ResearchExperiment).where(
                    ResearchExperiment.experiment_type == "oos_signal_diagnostics"
                )
            )
        )

    assert first.id == second.id
    assert len(experiments) == 1
    assert experiments[0].experiment_key == report.diagnostics_key
    assert experiments[0].results_json["source_experiment_key"] == report.source_experiment_key
