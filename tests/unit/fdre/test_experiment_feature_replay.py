from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import BaseModel
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchExperiment
from fdre.research.experiments.event_study import EventStudyConfig, EventWindow, MarketBar
from fdre.research.experiments.feature_replay import (
    RiskChurnFeatureReplayInput,
    build_risk_churn_feature_replay_input,
    persist_risk_churn_feature_replay_input,
    replay_risk_churn_feature_input,
)
from fdre.research.experiments.registry import (
    ResearchExperimentBundle,
    build_research_experiment_bundle,
    build_research_experiment_manifest,
    persist_research_experiment_manifest,
    replay_research_experiment,
    verify_research_experiment_bundle,
)
from fdre.research.experiments.replay_input import (
    WalkForwardReplayInput,
    build_walk_forward_replay_input,
    persist_walk_forward_replay_input,
    replay_walk_forward_input,
)
from fdre.research.experiments.walk_forward import WalkForwardConfig, WalkForwardStudyReport
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
from fdre.research.panel import FeatureLineage, PanelFeature, ResearchPanelRow


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _at(month: int, day: int = 10) -> datetime:
    year = 2023 if month == 12 else 2024
    return datetime(year, month, day, 15, tzinfo=UTC)


def _lineage(
    sources: list[str],
    times: dict[str, datetime],
) -> FeatureLineage:
    return FeatureLineage(
        feature="risk_changes",
        calculation_version="risk-changes-v1",
        parameters={},
        source_accessions=sources,
        source_available_at=times,
        max_source_available_at=max(times.values()),
        corpus_snapshot_id="snapshot-v1",
        lineage_id="a" * 64,
    )


def _row(
    ticker: str,
    accession: str,
    available_at: datetime,
    churn: float,
    lineage: FeatureLineage,
) -> ResearchPanelRow:
    feature_lineage: dict[PanelFeature, FeatureLineage] = {"risk_changes": lineage}
    return ResearchPanelRow(
        ticker=ticker,
        cik=f"cik-{ticker}",
        accession_number=accession,
        form_type="10-Q",
        period_end=available_at.date(),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=False,
        risk_churn_rate=churn,
        source_accessions=list(lineage.source_accessions),
        feature_provenance={},
        feature_lineage=feature_lineage,
        calculation_version="fdre-panel-v3",
        corpus_snapshot_id="snapshot-v1",
        max_source_available_at=lineage.max_source_available_at,
    )


def _panel_rows() -> tuple[list[ResearchPanelRow], dict[str, str]]:
    rows: list[ResearchPanelRow] = []
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    for rank, ticker in enumerate(tickers, start=1):
        dec = f"{ticker}-DEC"
        jan = f"{ticker}-JAN"
        feb = f"{ticker}-FEB"
        mar = f"{ticker}-MAR"
        dec_time = _at(12)
        jan_time = _at(1)
        feb_time = _at(2)
        mar_time = _at(3)
        base = rank / 20.0
        rows.extend(
            [
                _row(
                    ticker,
                    dec,
                    dec_time,
                    base,
                    _lineage([dec], {dec: dec_time}),
                ),
                _row(
                    ticker,
                    jan,
                    jan_time,
                    base + rank * 0.01,
                    _lineage([jan, dec], {jan: jan_time, dec: dec_time}),
                ),
                _row(
                    ticker,
                    feb,
                    feb_time,
                    base + rank * 0.025,
                    _lineage([feb, jan], {feb: feb_time, jan: jan_time}),
                ),
                _row(
                    ticker,
                    mar,
                    mar_time,
                    base + rank * 0.045,
                    _lineage([mar, feb], {mar: mar_time, feb: feb_time}),
                ),
            ]
        )
    return rows, {ticker: "Technology" for ticker in tickers}


def _bars() -> list[MarketBar]:
    bars: list[MarketBar] = []
    start = date(2024, 1, 1)
    for offset in range(121):
        session = start + timedelta(days=offset)
        bars.append(
            MarketBar(
                ticker="SPY",
                date=session,
                adjusted_close=100.0 + offset * 0.05,
            )
        )
        for rank, ticker in enumerate(("AAA", "BBB", "CCC", "DDD"), start=1):
            bars.append(
                MarketBar(
                    ticker=ticker,
                    date=session,
                    adjusted_close=50.0 + rank * 5.0 + offset * rank * 0.08,
                )
            )
    return bars


def _chain() -> tuple[
    RiskChurnFeatureReplayInput,
    WalkForwardReplayInput,
    WalkForwardStudyReport,
    OOSDiagnosticsReport,
    OOSSelectionSuiteReport,
    OOSImplementationReport,
    OOSPromotionReport,
    dict[str, set[str]],
]:
    rows, sectors = _panel_rows()
    feature_input = build_risk_churn_feature_replay_input(rows, sectors)
    events = replay_risk_churn_feature_input(feature_input)
    event_config = EventStudyConfig(
        benchmark_ticker="SPY",
        windows=[EventWindow(start=1, end=2)],
        bootstrap_iterations=100,
        random_seed=17,
    )
    walk_config = WalkForwardConfig(
        mode="expanding",
        train_months=1,
        validation_months=1,
        test_months=1,
        step_months=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 4, 1),
        min_train_events=1,
        min_validation_events=1,
        min_test_events=1,
    )
    definition: dict[str, object] = {"formula": "fixture risk churn"}
    walk_input = build_walk_forward_replay_input(
        events,
        _bars(),
        event_config,
        walk_config,
        signal_name=feature_input.signal_name,
        dataset_version=feature_input.dataset_version,
        feature_version=feature_input.feature_version,
        code_sha="deadbeef",
        definition=definition,
    )
    source = replay_walk_forward_input(walk_input)
    diagnostics = build_oos_diagnostics(
        source,
        OOSDiagnosticsConfig(
            n_quantiles=2,
            min_fold_observations=3,
            min_issuer_count=2,
            min_stability_folds=2,
        ),
    )
    selection = evaluate_oos_selection_suite(
        [diagnostics],
        OOSSelectionConfig(min_ic_folds=2),
    )
    implementation = evaluate_oos_implementation(
        source,
        selection,
        OOSImplementationConfig(
            n_quantiles=2,
            cost_bps=[0.0, 50.0],
            evaluation_cost_bps=0.0,
            min_rebalance_issuers=2,
            min_rebalances=1,
        ),
    )
    slices = {"sector:Technology": {"AAA", "BBB", "CCC", "DDD"}}
    promotion = evaluate_oos_promotion(
        source,
        diagnostics,
        selection,
        implementation,
        slices=slices,
        config=OOSPromotionConfig(
            min_slice_observations_per_fold=3,
            min_slice_folds=1,
            min_analyzable_slices=1,
            min_decay_horizons=1,
            max_single_name_weight=1.0,
        ),
    )
    return (
        feature_input,
        walk_input,
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        slices,
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, ResearchExperiment.__table__).create(engine)
    return Session(engine)


def _persist_child(session: Session, key: str, kind: str, report: BaseModel) -> None:
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


def _persist_chain(
    session: Session,
    feature_input: RiskChurnFeatureReplayInput,
    walk_input: WalkForwardReplayInput,
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    persist_risk_churn_feature_replay_input(session, feature_input)
    persist_walk_forward_replay_input(session, walk_input)
    reports: list[tuple[str, str, BaseModel]] = [
        (source.experiment_key, "walk_forward_signal_study", source),
        (diagnostics.diagnostics_key, "oos_signal_diagnostics", diagnostics),
        (selection.selection_key, "oos_signal_selection_suite", selection),
        (implementation.implementation_key, "oos_signal_implementation", implementation),
        (promotion.promotion_key, "oos_signal_promotion", promotion),
    ]
    for key, kind, report in reports:
        _persist_child(session, key, kind, report)
    session.commit()


def test_v4_recomputes_features_walk_forward_and_downstream_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_input, walk_input, source, diagnostics, selection, implementation, promotion, slices = (
        _chain()
    )
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
        walk_forward_input=walk_input,
        feature_input=feature_input,
    )
    assert manifest.registry_version == "research-experiment-registry-v4"
    assert [item.kind for item in manifest.artifacts] == [
        "feature_input",
        "walk_forward_input",
        "walk_forward",
        "oos_diagnostics",
        "oos_selection",
        "oos_implementation",
        "oos_promotion",
    ]

    with _session() as session:
        _persist_chain(
            session,
            feature_input,
            walk_input,
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
        )
        persist_research_experiment_manifest(session, manifest)
        database_replay = replay_research_experiment(session, manifest.experiment_id)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    assert database_replay.replay_mode == "feature_computational_replay"

    def _network_disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("feature computational replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _network_disabled)
    offline_replay = verify_research_experiment_bundle(bundle)
    assert offline_replay == database_replay


def test_v4_rejects_hash_consistent_forged_panel_feature_input() -> None:
    feature_input, walk_input, source, diagnostics, selection, implementation, promotion, slices = (
        _chain()
    )
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
        walk_forward_input=walk_input,
        feature_input=feature_input,
    )
    with _session() as session:
        _persist_chain(
            session,
            feature_input,
            walk_input,
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
        )
        persist_research_experiment_manifest(session, manifest)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    payload = bundle.model_dump(mode="json")
    artifacts = cast(list[dict[str, Any]], payload["artifacts"])
    feature_artifact = next(item for item in artifacts if item["kind"] == "feature_input")
    feature_payload = cast(dict[str, Any], feature_artifact["payload"])
    rows = cast(list[dict[str, Any]], feature_payload["rows"])
    rows[-1]["risk_churn_rate"] = float(rows[-1]["risk_churn_rate"]) + 0.5
    feature_without_key = {
        key: value for key, value in feature_payload.items() if key != "input_key"
    }
    forged_input_key = _digest(feature_without_key)
    feature_payload["input_key"] = forged_input_key
    forged_feature_sha = _digest(feature_payload)
    feature_artifact["experiment_key"] = forged_input_key
    feature_artifact["payload_sha256"] = forged_feature_sha

    manifest_payload = cast(dict[str, Any], payload["manifest"])
    manifest_artifacts = cast(list[dict[str, Any]], manifest_payload["artifacts"])
    feature_reference = next(
        item for item in manifest_artifacts if item["kind"] == "feature_input"
    )
    feature_reference["experiment_key"] = forged_input_key
    feature_reference["payload_sha256"] = forged_feature_sha
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

    with pytest.raises(ValueError, match="computational replay mismatch for scored_events"):
        verify_research_experiment_bundle(forged)


def test_feature_input_rejects_mixed_corpus_snapshots() -> None:
    rows, sectors = _panel_rows()
    rows[-1] = rows[-1].model_copy(update={"corpus_snapshot_id": "snapshot-v2"})

    with pytest.raises(ValueError, match="requires one corpus snapshot"):
        build_risk_churn_feature_replay_input(rows, sectors)
