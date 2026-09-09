from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import AnswerRun, RetrievalRun


def test_retrieval_telemetry_aggregates_latency_without_user_content(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'telemetry.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        session.add_all(
            [
                RetrievalRun(
                    query="private retrieval query one",
                    filters_json={"ticker": "SECRET"},
                    retriever_variant="hybrid",
                    latency_ms=100,
                    created_at=now - timedelta(minutes=4),
                ),
                RetrievalRun(
                    query="private retrieval query two",
                    filters_json=None,
                    retriever_variant="hybrid",
                    latency_ms=200,
                    created_at=now - timedelta(minutes=3),
                ),
                RetrievalRun(
                    query="private retrieval query three",
                    filters_json=None,
                    retriever_variant="sparse",
                    latency_ms=300,
                    created_at=now - timedelta(minutes=2),
                ),
                RetrievalRun(
                    query="private retrieval query four",
                    filters_json=None,
                    retriever_variant="hybrid",
                    latency_ms=400,
                    created_at=now - timedelta(minutes=1),
                ),
                AnswerRun(
                    question="private question one",
                    answer_text="private answer one",
                    abstained=False,
                    confidence=0.9,
                    latency_ms=500,
                    created_at=now - timedelta(minutes=3),
                ),
                AnswerRun(
                    question="private question two",
                    answer_text=None,
                    abstained=True,
                    abstention_reason="insufficient evidence",
                    confidence=None,
                    latency_ms=1000,
                    created_at=now - timedelta(minutes=2),
                ),
                AnswerRun(
                    question="private question three",
                    answer_text="private answer three",
                    abstained=False,
                    confidence=0.8,
                    latency_ms=1500,
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()

    response = _client(engine).get(
        "/operations/retrieval-telemetry",
        params={"sample_limit": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_runs_observed"] == 4
    assert payload["answer_runs_observed"] == 3
    assert payload["retrieval_latency"] == {
        "sample_size": 4,
        "p50_ms": 200,
        "p95_ms": 400,
        "mean_ms": 250.0,
        "min_ms": 100,
        "max_ms": 400,
    }
    variants = {
        item["retriever_variant"]: item["latency"]
        for item in payload["retrieval_variants"]
    }
    assert variants["hybrid"]["sample_size"] == 3
    assert variants["hybrid"]["p50_ms"] == 200
    assert variants["hybrid"]["p95_ms"] == 400
    assert variants["sparse"]["p50_ms"] == 300
    assert payload["answers"]["latency"]["p50_ms"] == 1000
    assert payload["answers"]["latency"]["p95_ms"] == 1500
    assert payload["answers"]["abstention_rate"] == 1 / 3
    assert payload["answers"]["mean_confidence"] == 0.85

    serialized = response.text
    for private_value in [
        "private retrieval query",
        "private question",
        "private answer",
        "SECRET",
        "insufficient evidence",
    ]:
        assert private_value not in serialized
    engine.dispose()


def test_retrieval_telemetry_sql_projection_excludes_sensitive_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'projection.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            RetrievalRun(
                query="do not project me",
                filters_json={"ticker": "PRIVATE"},
                retriever_variant="hybrid",
                latency_ms=120,
                created_at=now,
            )
        )
        session.add(
            AnswerRun(
                question="do not project this question",
                answer_text="do not project this answer",
                abstained=True,
                abstention_reason="private reason",
                confidence=0.4,
                latency_ms=240,
                trace_json={"private": True},
                created_at=now,
            )
        )
        session.commit()

    statements: list[str] = []

    def capture_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture_sql)
    try:
        response = _client(engine).get("/operations/retrieval-telemetry")
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)

    assert response.status_code == 200
    telemetry_sql = "\n".join(
        statement
        for statement in statements
        if "retrieval_runs" in statement or "answer_runs" in statement
    )
    assert telemetry_sql
    for sensitive_column in [
        "query",
        "filters_json",
        "question",
        "answer_text",
        "abstention_reason",
        "trace_json",
    ]:
        assert sensitive_column not in telemetry_sql
    engine.dispose()


def test_retrieval_telemetry_uses_independent_latest_n_samples_and_utc(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'latest-n.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        for index in range(51):
            created_at = now - timedelta(minutes=50 - index)
            session.add(
                RetrievalRun(
                    query=f"retrieval-{index}",
                    filters_json=None,
                    retriever_variant="hybrid",
                    latency_ms=(index + 1) * 10,
                    created_at=created_at,
                )
            )
            session.add(
                AnswerRun(
                    question=f"question-{index}",
                    answer_text=None,
                    abstained=index % 2 == 0,
                    confidence=0.5,
                    latency_ms=1000 + (index + 1) * 10,
                    created_at=created_at,
                )
            )
        session.commit()

    response = _client(engine).get(
        "/operations/retrieval-telemetry",
        params={"sample_limit": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sample_limit"] == 50
    assert payload["retrieval_runs_observed"] == 50
    assert payload["answer_runs_observed"] == 50
    assert payload["retrieval_latency"]["min_ms"] == 20
    assert payload["retrieval_latency"]["max_ms"] == 510

    earliest = _parse_datetime(payload["earliest_observed_at"])
    latest = _parse_datetime(payload["latest_observed_at"])
    generated = _parse_datetime(payload["generated_at"])
    assert earliest == now - timedelta(minutes=49)
    assert latest == now
    assert generated.utcoffset() == timedelta(0)
    assert earliest.utcoffset() == timedelta(0)
    assert latest.utcoffset() == timedelta(0)
    engine.dispose()


def test_retrieval_telemetry_enforces_sample_limit_bounds(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'bounds.db'}")
    Base.metadata.create_all(engine)
    client = _client(engine)

    assert client.get(
        "/operations/retrieval-telemetry",
        params={"sample_limit": 49},
    ).status_code == 422
    assert client.get(
        "/operations/retrieval-telemetry",
        params={"sample_limit": 5001},
    ).status_code == 422
    engine.dispose()


def test_retrieval_telemetry_handles_empty_history(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'empty-telemetry.db'}")
    Base.metadata.create_all(engine)

    response = _client(engine).get("/operations/retrieval-telemetry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_runs_observed"] == 0
    assert payload["answer_runs_observed"] == 0
    assert payload["retrieval_latency"]["sample_size"] == 0
    assert payload["retrieval_latency"]["p95_ms"] is None
    assert payload["retrieval_variants"] == []
    assert payload["answers"]["abstention_rate"] is None
    assert payload["answers"]["mean_confidence"] is None
    assert payload["earliest_observed_at"] is None
    assert payload["latest_observed_at"] is None
    engine.dispose()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _client(engine: Engine) -> TestClient:
    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    return TestClient(app)
