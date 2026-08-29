from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiment_registry import (
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    replay_research_experiment,
    verify_research_experiment,
)
from fdre.research.oos_diagnostics import OOSDiagnosticsReport
from fdre.research.oos_implementation import OOSImplementationConfig, OOSImplementationReport
from fdre.research.oos_promotion import (
    OOSPromotionConfig,
    OOSPromotionDecision,
    OOSPromotionReport,
)
from fdre.research.oos_selection import (
    OOSHypothesisDecision,
    OOSSelectionConfig,
    OOSSelectionSuiteReport,
)
from fdre.research.walk_forward import WalkForwardOOSObservation, WalkForwardStudyReport


def _artifacts() -> tuple[
    WalkForwardStudyReport,
    OOSDiagnosticsReport,
    OOSSelectionSuiteReport,
    OOSImplementationReport,
    OOSPromotionReport,
]:
    available = datetime(2024, 1, 10, 20, tzinfo=UTC)
    observation = WalkForwardOOSObservation(
        ticker="AAPL",
        accession_number="0000320193-24-000001",
        event_session=date(2024, 1, 11),
        window="1:21",
        window_end_session=date(2024, 2, 9),
        feature_value=0.3,
        outcome_value=0.02,
        available_at=available,
        max_source_available_at=available,
        feature_lineage_id="feature-lineage-1",
        fold_id="fold-1",
    )
    source = WalkForwardStudyReport.model_construct(
        experiment_key="walk-1",
        signal_name="risk_churn_acceleration",
        outcome_name="abnormal_return",
        sealed_oos=True,
        dataset_version="filings-v1",
        feature_version="risk-churn-v1",
        market_data_version="market-sha",
        universe_snapshot_id="universe-sha",
        feature_snapshot_id="feature-sha",
        code_sha="deadbeef",
        definition={"formula": "current churn minus prior churn"},
        feature_lineage_digest="lineage-sha",
        folds=[],
        oos_observations=[observation],
    )
    diagnostics = OOSDiagnosticsReport.model_construct(
        diagnostics_key="diagnostics-1",
        source_experiment_key="walk-1",
        signal_name=source.signal_name,
        outcome_name=source.outcome_name,
        sealed_oos=True,
        windows=[],
        folds=[],
    )
    selection = OOSSelectionSuiteReport.model_construct(
        selection_key="selection-1",
        config=OOSSelectionConfig(),
        decisions=[
            OOSHypothesisDecision.model_construct(
                hypothesis_id="hypothesis-1",
                source_experiment_key="walk-1",
                signal_name=source.signal_name,
                outcome_name=source.outcome_name,
                window="1:21",
                status="passes_statistical_gate",
            )
        ],
    )
    implementation = OOSImplementationReport.model_construct(
        implementation_key="implementation-1",
        source_experiment_key="walk-1",
        source_selection_key="selection-1",
        signal_name=source.signal_name,
        sealed_oos=True,
        config=OOSImplementationConfig(),
        windows=[],
    )
    decision = OOSPromotionDecision(
        hypothesis_id="hypothesis-1",
        signal_name=source.signal_name,
        window="1:21",
        status="promote",
        reasons=[],
        statistical_status="passes_statistical_gate",
        implementation_status="passes_implementation_gate",
        stress_cost_bps=50.0,
        stress_net_mean=0.01,
        max_single_name_weight=0.1,
        analyzable_slice_count=3,
        positive_slice_share=1.0,
        robustness_slices=[],
        signal_decay=[],
        positive_horizon_share=1.0,
    )
    promotion = OOSPromotionReport(
        promotion_key="promotion-1",
        source_experiment_key="walk-1",
        source_diagnostics_key="diagnostics-1",
        source_selection_key="selection-1",
        source_implementation_key="implementation-1",
        slice_snapshot_id="slices-sha",
        config=OOSPromotionConfig(),
        decisions=[decision],
    )
    return source, diagnostics, selection, implementation, promotion


def _persist_child(session: Session, key: str, kind: str, payload: dict[str, object]) -> None:
    session.add(
        ResearchExperiment(
            experiment_key=key,
            experiment_type=kind,
            dataset_version="dataset",
            feature_version="feature",
            code_sha="deadbeef",
            config_json={},
            results_json=payload,
        )
    )


def _persist_all_children(
    session: Session,
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    for key, kind, report in [
        (source.experiment_key, "walk_forward_signal_study", source),
        (diagnostics.diagnostics_key, "oos_signal_diagnostics", diagnostics),
        (selection.selection_key, "oos_signal_selection", selection),
        (implementation.implementation_key, "oos_signal_implementation", implementation),
        (promotion.promotion_key, "oos_signal_promotion", promotion),
    ]:
        _persist_child(session, key, kind, report.model_dump(mode="json"))
    session.commit()


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    ResearchExperiment.__table__.create(engine)
    return Session(engine)


def test_manifest_binds_full_research_lineage_and_is_deterministic() -> None:
    artifacts = _artifacts()
    first = build_research_experiment_manifest(*artifacts)
    second = build_research_experiment_manifest(*artifacts)

    assert first.experiment_id == second.experiment_id
    assert first.market_data_version == "market-sha"
    assert first.universe_snapshot_id == "universe-sha"
    assert first.feature_snapshot_id == "feature-sha"
    assert first.filing_lineage[0].accession_number == "0000320193-24-000001"
    assert [item.kind for item in first.artifacts] == [
        "walk_forward",
        "oos_diagnostics",
        "oos_selection",
        "oos_implementation",
        "oos_promotion",
    ]


def test_registry_verifies_and_replays_persisted_artifacts() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        _persist_all_children(
            session, source, diagnostics, selection, implementation, promotion
        )
        persist_research_experiment_manifest(session, manifest)

        verified = verify_research_experiment(session, manifest.experiment_id)
        replay = replay_research_experiment(session, manifest.experiment_id)

        assert verified.experiment_id == manifest.experiment_id
        assert replay.verified is True
        assert replay.artifact_count == 5
        assert replay.final_decisions[0]["status"] == "promote"


def test_registry_fails_closed_when_child_payload_is_tampered() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        _persist_all_children(
            session, source, diagnostics, selection, implementation, promotion
        )
        persist_research_experiment_manifest(session, manifest)

        row = session.query(ResearchExperiment).filter_by(
            experiment_key=promotion.promotion_key
        ).one()
        row.results_json = {**row.results_json, "slice_snapshot_id": "tampered"}
        session.commit()

        with pytest.raises(ValueError, match="artifact digest mismatch"):
            verify_research_experiment(session, manifest.experiment_id)


def test_manifest_identity_changes_with_market_or_universe_identity() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    first = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    changed = source.model_copy(update={"market_data_version": "market-sha-2"})
    second = build_research_experiment_manifest(
        changed, diagnostics, selection, implementation, promotion
    )

    assert first.experiment_id != second.experiment_id


def test_manifest_deduplicates_same_filing_across_windows() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    original = source.oos_observations[0]
    second = original.model_copy(update={"window": "1:63"})
    source = source.model_copy(update={"oos_observations": [original, second]})

    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )

    assert len(manifest.filing_lineage) == 1
    assert manifest.filing_lineage[0].accession_number == original.accession_number


def test_manifest_rejects_conflicting_lineage_for_same_accession() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    original = source.oos_observations[0]
    changed = original.model_copy(
        update={"max_source_available_at": datetime(2024, 1, 11, 20, tzinfo=UTC)}
    )
    source = source.model_copy(update={"oos_observations": [original, changed]})

    with pytest.raises(ValueError, match="conflicting filing lineage"):
        build_research_experiment_manifest(
            source, diagnostics, selection, implementation, promotion
        )


def test_registry_rejects_child_with_wrong_artifact_type() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        children = [
            (source.experiment_key, "wrong_type", source),
            (diagnostics.diagnostics_key, "oos_signal_diagnostics", diagnostics),
            (selection.selection_key, "oos_signal_selection", selection),
            (implementation.implementation_key, "oos_signal_implementation", implementation),
            (promotion.promotion_key, "oos_signal_promotion", promotion),
        ]
        for key, kind, report in children:
            _persist_child(session, key, kind, report.model_dump(mode="json"))
        session.commit()
        persist_research_experiment_manifest(session, manifest)

        with pytest.raises(ValueError, match="artifact type mismatch"):
            verify_research_experiment(session, manifest.experiment_id)


def test_registry_manifest_is_immutable_after_registration() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        persist_research_experiment_manifest(session, manifest)
        row = session.query(ResearchExperiment).filter_by(
            experiment_key=manifest.experiment_id
        ).one()
        row.results_json = {**row.results_json, "code_sha": "tampered"}
        session.commit()

        with pytest.raises(ValueError, match="payload mismatch"):
            persist_research_experiment_manifest(session, manifest)
