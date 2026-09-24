from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import QueryCanceled, UndefinedTable
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from apps.api.app.main import create_app


@pytest.mark.parametrize(
    "database_error, expected_status", [(QueryCanceled, 503), (UndefinedTable, 500)]
)
def test_thematic_scan_exposes_query_timeout_to_browser(
    monkeypatch: pytest.MonkeyPatch,
    database_error: type[Exception],
    expected_status: int,
) -> None:
    def fail_search(*args: object, **kwargs: object) -> None:
        raise OperationalError("private SQL", {}, database_error("private database detail"))

    monkeypatch.setattr("apps.api.app.routes.research.search_documents", fail_search)
    engine = create_engine("sqlite+pysqlite:///:memory:")

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/research/thematic-scan",
            json={"query": "data center constructions", "issuers": 6, "results_per_issuer": 1},
            headers={"Origin": "https://thefdre.com"},
        )

    assert response.status_code == expected_status
    assert "private" not in response.text
    if expected_status == 503:
        assert response.headers["access-control-allow-origin"] == "https://thefdre.com"
        assert "time limit" in response.json()["detail"]
