from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiments.event_study import EventStudyConfig, EventWindow
from fdre.research.experiments.registry import (
    ResearchExperimentBundle,
    build_research_experiment_bundle,
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    replay_research_experiment,
    verify_research_experiment_bundle,
)
from fdre.research.experiments.walk_forward import (
    WalkForwardConfig,
    WalkForwardOOSObservation,
    WalkForwardStudyReport,
)
from fdre.research.oos.diagnostics import (
    OOSDiagnosticsConfig,
    OOSDiagnosticsReport,
    build_oos_diagnostics,
)
from fdre.research.oos.implementation import (
    OOSImplementationConfig,
    OOSImplementationReport,
    evaluate_oos_implementation,
)
from fdre.research.oos.promotion import (
    OOSPromotionConfig,
    OOSPromotionReport,
    evaluate_oos_promotion,
)
from fdre.research.oos.selection import (
    OOSSelectionConfig,
    OOSSelectionSuiteReport,
    evaluate_oos_selection_suite,
)


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source() -> WalkForwardStudyReport:
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    observations: list[WalkForwardOOSObservation] = []
    for fold_number, event_session in enumerate(
        (date(2024, 1, 10), date(2024, 2, 12)), start=1
    ):
        for rank, ticker in enumerate(tickers, start=1):
            available = datetime.combine(
                event_session - timedelta(days=1),
                datetime.min.time(),
                tzinfo=UTC,
            )
            observations.append(
                WalkForwardOOSObservation(
                    ticker=ticker,
                    accession_number=f"{fold_number:02d}-{rank:02d}",
                    event_session=event_session,
                    window="1:21",
                    window_end_session=event_session + timedelta(days=30),
                    feature_value=float(rank),
                    outcome_value=rank / 100.0,
                    available_at=available,
                    max_source_available_at=available,
                    feature_lineage_id=f"lineage-{fold_number}-{rank}",
                    fold_id=f"fold-{fold_number}",
                )
            )
    return WalkForwardStudyReport(
        experiment_key="walk-forward-computational-replay",
        signal_name="fixture_signal",
        dataset_version="dataset-v1",
        feature_version="feature-v1",
        market_data_version="market-v1",
        universe_snapshot_id="universe-v1",
        feature_snapshot_id="feature-snapshot-v1",
        code_sha="deadbeef",
        definition={"formula": "fixture rank"},
        feature_lineage_digest="lineage-digest",
        feature_lineage_complete=True,
        event_study_config=EventStudyConfig(windows=[EventWindow(start=1, end=21)]),
        walk_forward_config=WalkForwardConfig(),
        fold_count=2,
        eligible_fold_count=2,
        oos_event_count=8,
        oos_observation_count=8,
        folds=[],
        oos_observations=observations,
    )


def _chain() -> tuple[
    WalkForwardStudyReport,
    OOSDiagnosticsReport,
    OOSSelectionSuiteReport,
    OOSImplementationReport,
    OOSPromotionReport,
    dict[str, set[str]],
]:
    source = _source()
    diagnostics = build_oos_diagnostics(
        source,
        OOSDiagnosticsConfig(
            n_quantiles=2,
            min_fold_observations=4,
            min_issuer_count=4,
            min_stability_folds=2,
        ),
    )
    selection = evaluate_oos_selection_suite(
        [diagnostics],
        OOSSelectionConfig(
            min_ic_folds=2,
            min_ic_mean=-1.0,
            min_icir=-100.0,
            min_positive_ic_share=0.0,
            min_quantile_monotonicity=-1.0,
            min_positive_long_short_share=0.0,
            min_long_short_mean=-1.0,
            max_fdr_q_value=1.0,
        ),
    )
    implementation = evaluate_oos_implementation(
        source,
        selection,
        OOSImplementationConfig(
            n_quantiles=2,
            execution_delay_sessions=1,
            cost_bps=[0.0, 50.0],
            evaluation_cost_bps=0.0,
            min_rebalance_issuers=4,
            min_rebalances=2,
            min_positive_net_fold_share=0.0,
            min_net_mean=-1.0,
            max_annualized_turnover=100.0,
        ),
    )
    slices = {"sector:fixture": {"AAA", "BBB", "CCC", "DDD"}}
    promotion = evaluate_oos_promotion(
        source,
        diagnostics,
        selection,
        implementation,
        slices=slices,
        config=OOSPromotionConfig(
            min_slice_observations_per_fold=3,
            min_slice_folds=2,
            min_analyzable_slices=1,
            min_positive_slice_share=0.0,
            stress_cost_bps=50.0,
            min_stress_net_mean=-1.0,
            min_decay_horizons=1,
            min_positive_horizon_share=0.0,
            max_single_name_weight=1.0,
        ),
    )
    return source, diagnostics, selection, implementation, promotion, slices


def _persist_children(
    session: Session,
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    reports = [
        (source.experiment_key, "walk_forward_signal_study", source),
        (diagnostics.diagnostics_key, "oos_signal_diagnostics", diagnostics),
        (selection.selection_key, "oos_signal_selection_suite", selection),
        (implementation.implementation_key, "oos_signal_implementation", implementation),
        (promotion.promotion_key, "oos_signal_promotion", promotion),
    ]
    for key, kind, report in reports:
        session.add(
            ResearchExperiment(
                experiment_key=key,
                experiment_type=kind,
                dataset_version="fixture",
                feature_version="fixture",
                code_sha="deadbeef",
                config_json={},
                results_json=report.model_dump(mode="json"),
            )
        )
    session.commit()


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, ResearchExperiment.__table__).create(engine)
    return Session(engine)


def test_v2_registry_recomputes_downstream_chain_in_database_and_offline() -> None:
    source, diagnostics, selection, implementation, promotion, slices = _chain()
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
    )
    assert manifest.registry_version == "research-experiment-registry-v2"
    assert manifest.promotion_slices == {
        "sector:fixture": ["AAA", "BBB", "CCC", "DDD"]
    }

    with _session() as session:
        _persist_children(session, source, diagnostics, selection, implementation, promotion)
        persist_research_experiment_manifest(session, manifest)
        database_replay = replay_research_experiment(session, manifest.experiment_id)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    assert database_replay.verified is True
    assert database_replay.replay_mode == "downstream_computational_replay"
    assert database_replay.recomputed_artifacts == [
        "oos_diagnostics",
        "oos_selection",
        "oos_implementation",
        "oos_promotion",
    ]
    offline_replay = verify_research_experiment_bundle(bundle)
    assert offline_replay == database_replay


def test_v2_computational_replay_rejects_hash_consistent_forged_bundle() -> None:
    source, diagnostics, selection, implementation, promotion, slices = _chain()
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
    )
    with _session() as session:
        _persist_children(session, source, diagnostics, selection, implementation, promotion)
        persist_research_experiment_manifest(session, manifest)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    payload = bundle.model_dump(mode="json")
    artifacts = cast(list[dict[str, Any]], payload["artifacts"])
    diagnostic_artifact = next(
        item for item in artifacts if item["kind"] == "oos_diagnostics"
    )
    diagnostic_payload = cast(dict[str, Any], diagnostic_artifact["payload"])
    windows = cast(list[dict[str, Any]], diagnostic_payload["windows"])
    windows[0]["ic_mean"] = float(windows[0]["ic_mean"]) - 0.25
    forged_diagnostic_sha = _digest(diagnostic_payload)
    diagnostic_artifact["payload_sha256"] = forged_diagnostic_sha

    manifest_payload = cast(dict[str, Any], payload["manifest"])
    manifest_artifacts = cast(list[dict[str, Any]], manifest_payload["artifacts"])
    diagnostic_reference = next(
        item for item in manifest_artifacts if item["kind"] == "oos_diagnostics"
    )
    diagnostic_reference["payload_sha256"] = forged_diagnostic_sha
    manifest_without_id = {
        key: value for key, value in manifest_payload.items() if key != "experiment_id"
    }
    forged_experiment_id = _digest(manifest_without_id)
    manifest_payload["experiment_id"] = forged_experiment_id
    payload["experiment_id"] = forged_experiment_id
    payload["bundle_sha256"] = _digest(
        {key: value for key, value in payload.items() if key != "bundle_sha256"}
    )
    forged = ResearchExperimentBundle.model_validate(payload)

    with pytest.raises(ValueError, match="computational replay mismatch for oos_diagnostics"):
        verify_research_experiment_bundle(forged)


def test_legacy_registry_remains_verifiable_without_claiming_computational_replay() -> None:
    source, diagnostics, selection, implementation, promotion, _ = _chain()
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
    )
    assert manifest.registry_version == "research-experiment-registry-v1"
    assert manifest.promotion_slices is None

    with _session() as session:
        _persist_children(session, source, diagnostics, selection, implementation, promotion)
        persist_research_experiment_manifest(session, manifest)
        replay = replay_research_experiment(session, manifest.experiment_id)

    assert replay.verified is True
    assert replay.replay_mode == "artifact_verification"
    assert replay.recomputed_artifacts == []


def test_v2_manifest_rejects_slice_memberships_that_do_not_match_promotion() -> None:
    source, diagnostics, selection, implementation, promotion, _ = _chain()
    with pytest.raises(ValueError, match="slice memberships do not match"):
        build_research_experiment_manifest(
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            promotion_slices={"sector:fixture": {"AAA", "BBB"}},
        )
