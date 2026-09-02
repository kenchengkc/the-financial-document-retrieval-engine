from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fdre.research.event_study import EventStudyConfig
from fdre.research.panel import (
    FEATURE_VERSION,
    FeatureLineage,
    ResearchPanel,
    ResearchPanelQuery,
    ResearchPanelRow,
    _feature_lineage_id,
    write_research_panel,
)
from fdre.research.screen import (
    ResearchScreenManifest,
    ResearchScreenPlan,
    ResearchScreenResponse,
    _feature_lineage_digest,
    _plan_hash,
)
from fdre.research.signal_study import SignalStudyReport
from fdre.research.verification import (
    verify_feature_lineage,
    verify_research_panel_export,
    verify_research_panel_lineage,
    verify_research_screen_lineage,
    verify_signal_study_lineage,
)


def _lineage(*, snapshot_id: str = "snapshot-1") -> FeatureLineage:
    available_at = datetime(2026, 2, 1, tzinfo=UTC)
    source_available_at = {"annual-2025": available_at}
    lineage_id = _feature_lineage_id(
        feature="filing_timing",
        calculation_version="filing-timing-v1",
        parameters={},
        source_accessions=["annual-2025"],
        source_available_at=source_available_at,
        corpus_snapshot_id=snapshot_id,
    )
    return FeatureLineage(
        feature="filing_timing",
        calculation_version="filing-timing-v1",
        source_accessions=["annual-2025"],
        source_available_at=source_available_at,
        max_source_available_at=available_at,
        corpus_snapshot_id=snapshot_id,
        lineage_id=lineage_id,
    )


def _panel() -> ResearchPanel:
    available_at = datetime(2026, 2, 1, tzinfo=UTC)
    lineage = _lineage()
    row = ResearchPanelRow(
        ticker="TEST",
        cik="0000000001",
        accession_number="annual-2025",
        form_type="10-K",
        period_end=date(2025, 12, 31),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=False,
        filing_delay_days=32,
        amendment_indicator=0,
        source_accessions=["annual-2025"],
        feature_provenance={"filing_features": ["annual-2025"]},
        feature_lineage={"filing_timing": lineage},
        calculation_version=FEATURE_VERSION,
        corpus_snapshot_id="snapshot-1",
        max_source_available_at=available_at,
    )
    return ResearchPanel(
        query=ResearchPanelQuery(tickers=["TEST"], features=["filing_timing"]),
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id="snapshot-1",
        rows=[row],
    )


def test_feature_and_panel_verification_reject_tampering() -> None:
    panel = _panel()
    verify_feature_lineage(panel.rows[0].feature_lineage["filing_timing"])
    verify_research_panel_lineage(panel)

    lineage = panel.rows[0].feature_lineage["filing_timing"].model_copy(
        update={"lineage_id": "0" * 64}
    )
    with pytest.raises(ValueError, match="Feature lineage hash mismatch"):
        verify_feature_lineage(lineage)

    wrong_snapshot = panel.model_copy(update={"corpus_snapshot_id": "other-snapshot"})
    with pytest.raises(ValueError, match="Panel row snapshot mismatch"):
        verify_research_panel_lineage(wrong_snapshot)


def test_panel_export_lineage_verifies_after_json_and_csv_round_trip(
    tmp_path: Path,
) -> None:
    panel = _panel()
    json_path = write_research_panel(tmp_path / "panel.json", panel, output_format="json")
    csv_path = write_research_panel(tmp_path / "panel.csv", panel, output_format="csv")

    assert verify_research_panel_export(json_path) == 1
    assert verify_research_panel_export(csv_path) == 1

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    lineage_payload = json.loads(payload[0]["feature_lineage"])
    lineage_payload["filing_timing"]["lineage_id"] = "0" * 64
    payload[0]["feature_lineage"] = json.dumps(lineage_payload, sort_keys=True)
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Feature lineage hash mismatch"):
        verify_research_panel_export(json_path)


def test_screen_verification_replays_plan_and_universe_digest() -> None:
    plan = ResearchScreenPlan(
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        semantic_query="artificial intelligence",
    )
    panel = ResearchPanel(
        query=ResearchPanelQuery(as_of=plan.as_of, form_types=["10-Q"]),
        feature_version=FEATURE_VERSION,
        corpus_snapshot_id="empty-snapshot",
        rows=[],
    )
    plan_hash = _plan_hash(plan)
    digest = _feature_lineage_digest(
        plan,
        plan_hash=plan_hash,
        corpus_snapshot_id=panel.corpus_snapshot_id,
        latest_rows={},
        rows_by_accession={},
    )
    response = ResearchScreenResponse(
        plan=plan,
        manifest=ResearchScreenManifest(
            plan_hash=plan_hash,
            feature_lineage_digest=digest,
            corpus_snapshot_id=panel.corpus_snapshot_id,
            feature_version=FEATURE_VERSION,
            universe_count=0,
            structured_match_count=0,
            semantic_search_calls=0,
            semantic_candidate_count=0,
            matched_count=0,
            max_information_timestamp=None,
        ),
        rows=[],
    )

    verify_research_screen_lineage(response, panel)

    bad_manifest = response.manifest.model_copy(
        update={"feature_lineage_digest": "0" * 64}
    )
    with pytest.raises(ValueError, match="Screen feature lineage digest mismatch"):
        verify_research_screen_lineage(
            response.model_copy(update={"manifest": bad_manifest}),
            panel,
        )


def test_complete_signal_report_reproduces_digest_and_experiment_key() -> None:
    lineage_by_accession = {"annual-2025": "a" * 64}
    pairs = sorted(lineage_by_accession.items())
    lineage_digest = hashlib.sha256(
        json.dumps(pairs, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    config = EventStudyConfig()
    manifest: dict[str, object] = {
        "signal_name": "filing delay",
        "outcome_name": "abnormal_return",
        "bootstrap_unit": "issuer",
        "n_quantiles": 5,
        "dataset_version": "dataset-v1",
        "feature_version": FEATURE_VERSION,
        "code_sha": "deadbeef",
        "neutralization": "none",
        "definition": {},
        "config": config.model_dump(mode="json"),
        "events": ["annual-2025"],
        "feature_lineage_by_accession": lineage_by_accession,
        "feature_lineage_digest": lineage_digest,
        "feature_lineage_complete": True,
    }
    experiment_key = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    ).hexdigest()
    report = SignalStudyReport(
        experiment_key=experiment_key,
        signal_name="filing delay",
        n_quantiles=5,
        dataset_version="dataset-v1",
        feature_version=FEATURE_VERSION,
        code_sha="deadbeef",
        feature_lineage_by_accession=lineage_by_accession,
        feature_lineage_digest=lineage_digest,
        feature_lineage_complete=True,
        config=config,
        event_count=1,
        results=[],
    )

    verify_signal_study_lineage(report)

    with pytest.raises(ValueError, match="Signal feature lineage digest mismatch"):
        verify_signal_study_lineage(
            report.model_copy(update={"feature_lineage_digest": "0" * 64})
        )
    with pytest.raises(ValueError, match="Incomplete signal lineage"):
        verify_signal_study_lineage(
            report.model_copy(
                update={
                    "feature_lineage_complete": False,
                    "feature_lineage_digest": lineage_digest,
                }
            )
        )
