from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document, DocumentElement, ResearchExperiment
from fdre.research.experiments.event_study import EventStudyConfig, EventWindow, MarketBar
from fdre.research.experiments.feature_replay import (
    RiskChurnFeatureReplayInput,
    build_risk_churn_feature_replay_input,
    persist_risk_churn_feature_replay_input,
    replay_risk_churn_feature_input,
)
from fdre.research.experiments.panel_replay import (
    RiskChurnPanelReplayInput,
    build_risk_churn_panel_replay_input,
    persist_risk_churn_panel_replay_input,
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
from fdre.research.panel import ResearchPanelQuery, build_research_panel


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _risk_passages(prefix: str, changed: int) -> tuple[list[str], list[str]]:
    baseline = [f"{prefix} stable risk {index}" for index in range(50)]
    current = baseline[: 50 - changed] + [
        f"{prefix} new risk {index}" for index in range(changed)
    ]
    return baseline, current


def _document(
    company: Company,
    *,
    accession: str,
    period_end: date,
    available_at: datetime,
    passages: list[str],
) -> Document:
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-Q",
        filing_date=available_at.date(),
        period_end_date=period_end,
        accepted_at=available_at,
        available_at=available_at,
        accession_number=accession,
        sha256_hash=_digest({"accession": accession, "passages": passages}),
    )
    for order, passage in enumerate(passages, start=1):
        document.elements.append(
            DocumentElement(
                element_type="text",
                section="Risk Factors",
                text=passage,
                reading_order=order,
            )
        )
    return document


def _build_source_panel(session: Session):
    tickers = ("AAA", "BBB", "CCC", "DDD")
    current_periods = (
        date(2024, 1, 31),
        date(2024, 4, 30),
        date(2024, 7, 31),
        date(2024, 10, 31),
    )
    current_available = (
        datetime(2024, 2, 10, 15, tzinfo=UTC),
        datetime(2024, 5, 10, 15, tzinfo=UTC),
        datetime(2024, 8, 10, 15, tzinfo=UTC),
        datetime(2024, 11, 10, 15, tzinfo=UTC),
    )
    change_scale = (1, 2, 4, 7)
    for rank, ticker in enumerate(tickers, start=1):
        company = Company(
            ticker=ticker,
            cik=f"{rank:010d}",
            name=f"Company {ticker}",
            sector="Technology",
        )
        for quarter, (period_end, available_at, scale) in enumerate(
            zip(current_periods, current_available, change_scale, strict=True),
            start=1,
        ):
            prior_end = date(period_end.year - 1, period_end.month, period_end.day)
            prior_available = available_at.replace(year=available_at.year - 1)
            prior, current = _risk_passages(
                f"{ticker}-Q{quarter}",
                changed=rank * scale,
            )
            _document(
                company,
                accession=f"{ticker}-Q{quarter}-2023",
                period_end=prior_end,
                available_at=prior_available,
                passages=prior,
            )
            _document(
                company,
                accession=f"{ticker}-Q{quarter}-2024",
                period_end=period_end,
                available_at=available_at,
                passages=current,
            )
        session.add(company)
    session.commit()
    return build_research_panel(
        session,
        ResearchPanelQuery(
            tickers=list(tickers),
            form_types=["10-Q"],
            features=["risk_changes"],
            as_of=datetime(2024, 12, 1, tzinfo=UTC),
            limit=10_000,
        ),
    )


def _bars() -> list[MarketBar]:
    bars: list[MarketBar] = []
    start = date(2024, 1, 1)
    for offset in range(397):
        session_date = start + timedelta(days=offset)
        bars.append(
            MarketBar(
                ticker="SPY",
                date=session_date,
                adjusted_close=100.0 + offset * 0.05,
            )
        )
        for rank, ticker in enumerate(("AAA", "BBB", "CCC", "DDD"), start=1):
            bars.append(
                MarketBar(
                    ticker=ticker,
                    date=session_date,
                    adjusted_close=50.0 + rank * 5.0 + offset * rank * 0.08,
                )
            )
    return bars


def _chain(session: Session) -> tuple[
    RiskChurnPanelReplayInput,
    RiskChurnFeatureReplayInput,
    WalkForwardReplayInput,
    WalkForwardStudyReport,
    OOSDiagnosticsReport,
    OOSSelectionSuiteReport,
    OOSImplementationReport,
    OOSPromotionReport,
    dict[str, set[str]],
]:
    panel = _build_source_panel(session)
    panel_input = build_risk_churn_panel_replay_input(session, panel)
    sectors = dict.fromkeys(("AAA", "BBB", "CCC", "DDD"), "Technology")
    feature_input = build_risk_churn_feature_replay_input(panel.rows, sectors)
    events = replay_risk_churn_feature_input(feature_input)
    event_config = EventStudyConfig(
        benchmark_ticker="SPY",
        windows=[EventWindow(start=1, end=2)],
        bootstrap_iterations=100,
        random_seed=17,
    )
    walk_config = WalkForwardConfig(
        mode="expanding",
        train_months=3,
        validation_months=3,
        test_months=3,
        step_months=3,
        start_date=date(2024, 2, 1),
        end_date=date(2025, 2, 1),
        min_train_events=1,
        min_validation_events=1,
        min_test_events=1,
    )
    definition: dict[str, object] = {"formula": "fixture risk churn acceleration"}
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
            min_stability_folds=1,
        ),
    )
    selection = evaluate_oos_selection_suite(
        [diagnostics],
        OOSSelectionConfig(min_ic_folds=1),
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
        panel_input,
        feature_input,
        walk_input,
        source,
        diagnostics,
        selection,
        implementation,
        promotion,
        slices,
    )


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
    panel_input: RiskChurnPanelReplayInput,
    feature_input: RiskChurnFeatureReplayInput,
    walk_input: WalkForwardReplayInput,
    source: WalkForwardStudyReport,
    diagnostics: OOSDiagnosticsReport,
    selection: OOSSelectionSuiteReport,
    implementation: OOSImplementationReport,
    promotion: OOSPromotionReport,
) -> None:
    persist_risk_churn_panel_replay_input(session, panel_input)
    persist_risk_churn_feature_replay_input(session, feature_input)
    persist_walk_forward_replay_input(session, walk_input)
    for key, kind, report in (
        (source.experiment_key, "walk_forward_signal_study", source),
        (diagnostics.diagnostics_key, "oos_signal_diagnostics", diagnostics),
        (selection.selection_key, "oos_signal_selection_suite", selection),
        (implementation.implementation_key, "oos_signal_implementation", implementation),
        (promotion.promotion_key, "oos_signal_promotion", promotion),
    ):
        _persist_child(session, key, kind, report)
    session.commit()


def test_v5_replays_panel_features_and_downstream_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        (
            panel_input,
            feature_input,
            walk_input,
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            slices,
        ) = _chain(session)
        manifest = build_research_experiment_manifest(
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            promotion_slices=slices,
            walk_forward_input=walk_input,
            feature_input=feature_input,
            panel_input=panel_input,
        )
        assert manifest.registry_version == "research-experiment-registry-v5"
        assert [item.kind for item in manifest.artifacts] == [
            "panel_input",
            "feature_input",
            "walk_forward_input",
            "walk_forward",
            "oos_diagnostics",
            "oos_selection",
            "oos_implementation",
            "oos_promotion",
        ]
        _persist_chain(
            session,
            panel_input,
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

    assert database_replay.replay_mode == "panel_computational_replay"

    def _network_disabled(*args: object, **kwargs: object) -> None:
        raise AssertionError("panel computational replay attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _network_disabled)
    offline_replay = verify_research_experiment_bundle(bundle)
    assert offline_replay == database_replay


def test_v5_rejects_hash_consistent_forged_source_passage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        (
            panel_input,
            feature_input,
            walk_input,
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            slices,
        ) = _chain(session)
        manifest = build_research_experiment_manifest(
            source,
            diagnostics,
            selection,
            implementation,
            promotion,
            promotion_slices=slices,
            walk_forward_input=walk_input,
            feature_input=feature_input,
            panel_input=panel_input,
        )
        _persist_chain(
            session,
            panel_input,
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
    panel_artifact = next(item for item in artifacts if item["kind"] == "panel_input")
    panel_payload = cast(dict[str, Any], panel_artifact["payload"])
    elements = cast(list[dict[str, Any]], panel_payload["risk_factor_elements"])
    elements[-1]["text"] = "Forged risk disclosure that did not exist in the frozen source."
    panel_without_key = {
        key: value for key, value in panel_payload.items() if key != "input_key"
    }
    forged_input_key = _digest(panel_without_key)
    panel_payload["input_key"] = forged_input_key
    forged_panel_sha = _digest(panel_payload)
    panel_artifact["experiment_key"] = forged_input_key
    panel_artifact["payload_sha256"] = forged_panel_sha

    manifest_payload = cast(dict[str, Any], payload["manifest"])
    manifest_artifacts = cast(list[dict[str, Any]], manifest_payload["artifacts"])
    panel_reference = next(
        item for item in manifest_artifacts if item["kind"] == "panel_input"
    )
    panel_reference["experiment_key"] = forged_input_key
    panel_reference["payload_sha256"] = forged_panel_sha
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

    with pytest.raises(ValueError, match="panel replay row digest mismatch"):
        verify_research_experiment_bundle(forged)
