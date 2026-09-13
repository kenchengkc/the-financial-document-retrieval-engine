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
from fdre.research.experiments.event_study import (
    EventStudyConfig,
    EventWindow,
    FilingEvent,
    MarketBar,
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


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _inputs() -> tuple[
    list[FilingEvent],
    list[MarketBar],
    EventStudyConfig,
    WalkForwardConfig,
]:
    tickers = ["AAA", "BBB", "CCC", "DDD"]
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
        for rank, ticker in enumerate(tickers, start=1):
            bars.append(
                MarketBar(
                    ticker=ticker,
                    date=session,
                    adjusted_close=50.0 + rank * 5.0 + offset * rank * 0.08,
                )
            )

    events: list[FilingEvent] = []
    for month, day in ((1, 10), (2, 10), (3, 10)):
        for rank, ticker in enumerate(tickers, start=1):
            available = datetime(2024, month, day, 15, tzinfo=UTC)
            events.append(
                FilingEvent(
                    ticker=ticker,
                    accession_number=f"2024-{month:02d}-{rank:02d}",
                    available_at=available,
                    max_source_available_at=available,
                    feature_value=float(rank),
                )
            )

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
    return events, bars, event_config, walk_config


def _chain() -> tuple[
    WalkForwardReplayInput,
    WalkForwardStudyReport,
    OOSDiagnosticsReport,
    OOSSelectionSuiteReport,
    OOSImplementationReport,
    OOSPromotionReport,
    dict[str, set[str]],
]:
    events, bars, event_config, walk_config = _inputs()
    definition: dict[str, object] = {"formula": "fixture rank"}
    replay_input = build_walk_forward_replay_input(
        events,
        bars,
        event_config,
        walk_config,
        signal_name="fixture_signal",
        dataset_version="dataset-v1",
        feature_version="feature-v1",
        code_sha="deadbeef",
        definition=definition,
    )
    source = replay_walk_forward_input(replay_input)
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
    slices = {"sector:fixture": {"AAA", "BBB", "CCC", "DDD"}}
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
    return replay_input, source, diagnostics, selection, implementation, promotion, slices


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, ResearchExperiment.__table__).create(engine)
    return Session(engine)


def _persist_child(
    session: Session,
    key: str,
    kind: str,
    report: BaseModel,
) -> None:
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
    replay_input: WalkForwardReplayInput,
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    persist_walk_forward_replay_input(session, replay_input)
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


def test_v3_recomputes_walk_forward_and_downstream_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay_input, source, diagnostics, selection, implementation, promotion, slices = _chain()
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
        walk_forward_input=replay_input,
    )
    assert manifest.registry_version == "research-experiment-registry-v3"
    assert [item.kind for item in manifest.artifacts] == [
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
            replay_input,
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
        )
        persist_research_experiment_manifest(session, manifest)
        database_replay = replay_research_experiment(session, manifest.experiment_id)
        bundle = build_research_experiment_bundle(session, manifest.experiment_id)

    assert database_replay.replay_mode == "walk_forward_computational_replay"
    assert database_replay.recomputed_artifacts == [
        "walk_forward",
        "oos_diagnostics",
        "oos_selection",
        "oos_implementation",
        "oos_promotion",
    ]

    def _network_disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("computational replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _network_disabled)
    offline_replay = verify_research_experiment_bundle(bundle)
    assert offline_replay == database_replay


def test_v3_rejects_hash_consistent_forged_walk_forward_artifact() -> None:
    replay_input, source, diagnostics, selection, implementation, promotion, slices = _chain()
    manifest = build_research_experiment_manifest(
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        promotion_slices=slices,
        walk_forward_input=replay_input,
    )
    with _session() as session:
        _persist_chain(
            session,
            replay_input,
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
    source_artifact = next(item for item in artifacts if item["kind"] == "walk_forward")
    source_payload = cast(dict[str, Any], source_artifact["payload"])
    source_payload["oos_observation_count"] = int(source_payload["oos_observation_count"]) + 1
    forged_source_sha = _digest(source_payload)
    source_artifact["payload_sha256"] = forged_source_sha

    manifest_payload = cast(dict[str, Any], payload["manifest"])
    manifest_artifacts = cast(list[dict[str, Any]], manifest_payload["artifacts"])
    source_reference = next(
        item for item in manifest_artifacts if item["kind"] == "walk_forward"
    )
    source_reference["payload_sha256"] = forged_source_sha
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

    with pytest.raises(ValueError, match="computational replay mismatch for walk_forward"):
        verify_research_experiment_bundle(forged)


def test_walk_forward_replay_input_detects_market_payload_tampering() -> None:
    replay_input, *_ = _chain()
    changed_bar = replay_input.bars[0].model_copy(
        update={"adjusted_close": replay_input.bars[0].adjusted_close + 1.0}
    )
    tampered = replay_input.model_copy(
        update={"bars": [changed_bar, *replay_input.bars[1:]]}
    )

    with pytest.raises(ValueError, match="replay input digest mismatch"):
        replay_walk_forward_input(tampered)


def test_v3_manifest_rejects_replay_input_bound_to_different_source() -> None:
    replay_input, source, diagnostics, selection, implementation, promotion, slices = _chain()
    mismatched = replay_input.model_copy(update={"dataset_version": "dataset-v2"})

    with pytest.raises(ValueError, match="dataset version mismatch"):
        build_research_experiment_manifest(
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            promotion_slices=slices,
            walk_forward_input=mismatched,
        )
