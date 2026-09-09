from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import EventStudyConfig
from fdre.research.experiments.registry import (
    ResearchExperimentBundle,
    build_research_experiment_bundle,
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    read_research_experiment_bundle,
    replay_research_experiment,
    verify_research_experiment,
    verify_research_experiment_bundle,
    write_research_experiment_bundle,
)
from fdre.research.oos.diagnostics import OOSDiagnosticsConfig, OOSDiagnosticsReport
from fdre.research.oos.implementation import OOSImplementationConfig, OOSImplementationReport
from fdre.research.oos.promotion import (
    OOSPromotionConfig,
    OOSPromotionDecision,
    OOSPromotionReport,
)
from fdre.research.oos.selection import (
    OOSHypothesisDecision,
    OOSSelectionConfig,
    OOSSelectionSuiteReport,
)
from fdre.research.walk_forward import (
    WalkForwardConfig,
    WalkForwardOOSObservation,
    WalkForwardStudyReport,
)


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
        event_study_config=EventStudyConfig(),
        walk_forward_config=WalkForwardConfig(),
        fold_count=0,
        eligible_fold_count=0,
        oos_event_count=1,
        oos_observation_count=1,
        folds=[],
        oos_observations=[observation],
    )
    diagnostics = OOSDiagnosticsReport.model_construct(
        diagnostics_key="diagnostics-1",
        source_experiment_key="walk-1",
        signal_name=source.signal_name,
        outcome_name=source.outcome_name,
        sealed_oos=True,
        status="ready",
        dataset_version=source.dataset_version,
        feature_version=source.feature_version,
        market_data_version=source.market_data_version,
        universe_snapshot_id=source.universe_snapshot_id,
        feature_snapshot_id=source.feature_snapshot_id,
        code_sha=source.code_sha,
        source_eligible_fold_count=source.eligible_fold_count,
        source_oos_event_count=source.oos_event_count,
        source_oos_observation_count=source.oos_observation_count,
        config=OOSDiagnosticsConfig(),
        windows=[],
        folds=[],
    )
    selection = OOSSelectionSuiteReport.model_construct(
        selection_key="selection-1",
        declared_hypothesis_count=1,
        tested_hypothesis_count=1,
        passing_count=1,
        rejected_count=0,
        insufficient_count=0,
        input_diagnostics_keys=[diagnostics.diagnostics_key],
        source_code_digest="fixture-code-digest",
        config=OOSSelectionConfig(),
        decisions=[
            OOSHypothesisDecision.model_construct(
                hypothesis_id="hypothesis-1",
                source_diagnostics_key=diagnostics.diagnostics_key,
                source_experiment_key="walk-1",
                signal_name=source.signal_name,
                outcome_name=source.outcome_name,
                window="1:21",
                status="passes_statistical_gate",
                ic_fold_count=4,
                ic_mean=0.05,
                icir=1.0,
                positive_ic_share=1.0,
                quantile_monotonicity_mean=0.8,
                long_short_mean=0.01,
                positive_long_short_share=1.0,
                raw_p_value=0.01,
                adjusted_q_value=0.01,
                inference_method="test_fixture",
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
        (selection.selection_key, "oos_signal_selection_suite", selection),
        (implementation.implementation_key, "oos_signal_implementation", implementation),
        (promotion.promotion_key, "oos_signal_promotion", promotion),
    ]:
        _persist_child(session, key, kind, report.model_dump(mode="json"))
    session.commit()


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, ResearchExperiment.__table__).create(engine)
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
            (selection.selection_key, "oos_signal_selection_suite", selection),
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


def test_portable_bundle_is_deterministic_and_verifies_offline(tmp_path: Path) -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        _persist_all_children(
            session, source, diagnostics, selection, implementation, promotion
        )
        persist_research_experiment_manifest(session, manifest)
        first = build_research_experiment_bundle(session, manifest.experiment_id)
        second = build_research_experiment_bundle(session, manifest.experiment_id)

    assert first == second
    assert first.bundle_sha256 == second.bundle_sha256
    assert [item.kind for item in first.artifacts] == [
        "walk_forward",
        "oos_diagnostics",
        "oos_selection",
        "oos_implementation",
        "oos_promotion",
    ]

    destination = write_research_experiment_bundle(tmp_path / "bundle.json", first)
    loaded = read_research_experiment_bundle(destination)
    replay = verify_research_experiment_bundle(
        loaded,
        expected_experiment_id=manifest.experiment_id,
    )

    assert replay.verified is True
    assert replay.artifact_count == 5
    assert replay.final_decisions[0]["status"] == "promote"


def test_portable_bundle_rejects_substituted_root() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        _persist_all_children(
            session, source, diagnostics, selection, implementation, promotion
        )
        persist_research_experiment_manifest(session, manifest)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    with pytest.raises(ValueError, match="does not match expected experiment id"):
        verify_research_experiment_bundle(
            bundle,
            expected_experiment_id="0" * 64,
        )


def test_portable_bundle_detects_inner_artifact_tampering_after_outer_rehash() -> None:
    source, diagnostics, selection, implementation, promotion = _artifacts()
    manifest = build_research_experiment_manifest(
        source, diagnostics, selection, implementation, promotion
    )
    with _session() as session:
        _persist_all_children(
            session, source, diagnostics, selection, implementation, promotion
        )
        persist_research_experiment_manifest(session, manifest)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    payload = bundle.model_dump(mode="json")
    artifacts = cast(list[dict[str, object]], payload["artifacts"])
    promotion_artifact = artifacts[-1]
    promotion_payload = cast(dict[str, object], promotion_artifact["payload"])
    promotion_payload["slice_snapshot_id"] = "tampered"
    payload["bundle_sha256"] = _digest(
        {key: value for key, value in payload.items() if key != "bundle_sha256"}
    )
    tampered = ResearchExperimentBundle.model_validate(payload)

    with pytest.raises(ValueError, match="artifact digest mismatch for oos_promotion"):
        verify_research_experiment_bundle(tampered)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
