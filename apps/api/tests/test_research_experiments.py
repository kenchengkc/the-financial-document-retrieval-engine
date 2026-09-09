from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import ResearchExperiment


def test_experiment_provenance_lists_and_inspects_registered_manifests() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    older_id = "1" * 64
    newer_id = "2" * 64
    with Session(engine) as session:
        session.add_all(
            [
                _manifest_row(older_id, signal_name="risk_churn"),
                _manifest_row(newer_id, signal_name="disclosure_change"),
            ]
        )
        session.commit()

    client = _client(engine)
    listing = client.get("/research/experiments", params={"limit": 1})

    assert listing.status_code == 200
    experiments = listing.json()["experiments"]
    assert len(experiments) == 1
    assert experiments[0]["experiment_id"] == newer_id
    assert experiments[0]["signal_name"] == "disclosure_change"
    assert experiments[0]["artifact_count"] == 0
    assert experiments[0]["filing_lineage_count"] == 0
    assert experiments[0]["code_sha"] == "abc123"

    detail = client.get(f"/research/experiments/{older_id}")
    assert detail.status_code == 200
    assert detail.json()["experiment_id"] == older_id
    assert detail.json()["universe_snapshot_id"] == "universe-snapshot"
    assert detail.json()["statistical_assumptions"] == {"min_folds": 4}


def test_experiment_provenance_fails_closed_for_missing_or_tampered_manifest() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    experiment_id = "3" * 64
    with Session(engine) as session:
        session.add(_manifest_row(experiment_id, signal_name="risk_churn"))
        session.commit()

    client = _client(engine)
    missing = client.get(f"/research/experiments/{'f' * 64}")
    assert missing.status_code == 404
    assert "missing research experiment artifact" in missing.json()["detail"]

    replay = client.get(f"/research/experiments/{experiment_id}/verify")
    assert replay.status_code == 409
    assert replay.json()["detail"] == "research experiment manifest digest mismatch"

    bundle = client.get(f"/research/experiments/{experiment_id}/bundle")
    assert bundle.status_code == 409
    assert bundle.json()["detail"] == "research experiment manifest digest mismatch"

    invalid = client.get("/research/experiments/not-a-sha")
    assert invalid.status_code == 422


def _client(engine: Engine) -> TestClient:
    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    return TestClient(app)


def _manifest_row(experiment_id: str, *, signal_name: str) -> ResearchExperiment:
    payload = {
        "experiment_id": experiment_id,
        "registry_version": "research-experiment-registry-v1",
        "signal_name": signal_name,
        "outcome_name": "abnormal_return",
        "signal_definition": {"description": "test signal"},
        "dataset_version": "dataset-v1",
        "feature_version": "feature-v1",
        "market_data_version": "market-v1",
        "universe_snapshot_id": "universe-snapshot",
        "feature_snapshot_id": "feature-snapshot",
        "code_sha": "abc123",
        "feature_lineage_digest": "lineage-digest",
        "fold_schedule": [],
        "filing_lineage": [],
        "implementation_assumptions": {"cost_bps": 10},
        "statistical_assumptions": {"min_folds": 4},
        "robustness_assumptions": {"require_sector_stability": True},
        "slice_snapshot_id": "slice-snapshot",
        "artifacts": [],
        "final_decisions": [{"status": "INSUFFICIENT"}],
    }
    return ResearchExperiment(
        experiment_key=experiment_id,
        experiment_type="research_experiment_manifest",
        dataset_version="dataset-v1",
        feature_version="feature-v1",
        code_sha="abc123",
        config_json={"registry_version": "research-experiment-registry-v1"},
        results_json=payload,
    )
