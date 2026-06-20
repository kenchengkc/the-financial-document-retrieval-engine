from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import ResearchExperiment


def test_signal_studies_returns_latest_distinct_signal_outcomes() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                _experiment(
                    "old-disclosure",
                    "disclosure_similarity",
                    "abnormal_return",
                    event_count=40,
                ),
                _experiment(
                    "risk-vol",
                    "risk_factor_expansion",
                    "realized_volatility",
                    event_count=55,
                ),
                _experiment(
                    "new-disclosure",
                    "disclosure_similarity",
                    "abnormal_return",
                    event_count=80,
                ),
            ]
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    response = TestClient(app).get("/research/signal-studies")

    assert response.status_code == 200
    studies = response.json()["studies"]
    assert [study["experiment_key"] for study in studies] == [
        "new-disclosure",
        "risk-vol",
    ]
    assert studies[0]["report"]["event_count"] == 80
    assert studies[1]["report"]["outcome_name"] == "realized_volatility"


def _experiment(
    key: str,
    signal_name: str,
    outcome_name: str,
    *,
    event_count: int,
) -> ResearchExperiment:
    return ResearchExperiment(
        experiment_key=key,
        experiment_type="signal_study",
        dataset_version="dataset",
        feature_version="feature",
        code_sha="abc123",
        config_json={"windows": ["0:1"]},
        results_json={
            "experiment_key": key,
            "signal_name": signal_name,
            "outcome_name": outcome_name,
            "n_quantiles": 5,
            "dataset_version": "dataset",
            "feature_version": "feature",
            "code_sha": "abc123",
            "config": {"benchmark_ticker": "SPY", "confidence_level": 0.95},
            "event_count": event_count,
            "results": [],
        },
    )
