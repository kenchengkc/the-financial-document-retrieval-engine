from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.services.retrieval_service import SearchServiceResult
from fdre.research.panel import FEATURE_VERSION, ResearchPanel, ResearchPanelQuery
from fdre.retrieval.query import PreprocessedQuery, RetrievalCandidate, SearchFilters


def test_research_preview_and_example_scan_use_snapshot_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    calls = {"panel": 0, "scan": 0}

    def fake_panel(_session: Session, query: ResearchPanelQuery) -> ResearchPanel:
        calls["panel"] += 1
        return ResearchPanel(
            query=query,
            feature_version=FEATURE_VERSION,
            corpus_snapshot_id="snapshot",
            rows=[],
        )

    def fake_search(
        _session: Session,
        _settings: Settings,
        *,
        query: str,
        filters: SearchFilters,
        top_k: int,
    ) -> SearchServiceResult:
        del top_k
        calls["scan"] += 1
        return SearchServiceResult(
            preprocessed=PreprocessedQuery(
                original_query=query,
                rewritten_queries=[query],
                filters=filters,
                routes=["text"],
            ),
            candidates=[
                RetrievalCandidate(
                    chunk_id=1,
                    text="Currency headwinds reduced reported revenue.",
                    metadata={"ticker": "TEST", "company_name": "Test Company"},
                    hybrid_score=0.8,
                )
            ],
            latency_ms=750,
        )

    monkeypatch.setattr("apps.api.app.routes.research.build_research_panel", fake_panel)
    monkeypatch.setattr("apps.api.app.routes.research.search_documents", fake_search)

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        RESEARCH_CACHE_TTL_SECONDS=21600,
    )
    client = TestClient(app)

    first_panel = client.get("/research/panel", params={"limit": 25})
    second_panel = client.get("/research/panel", params={"limit": 25})
    oversized_panel = client.get("/research/panel", params={"limit": 26})
    request = {
        "query": "foreign exchange and currency headwinds",
        "issuers": 6,
        "results_per_issuer": 1,
    }
    first_scan = client.post("/research/thematic-scan", json=request)
    second_scan = client.post("/research/thematic-scan", json=request)

    assert first_panel.headers["X-Cache"] == "MISS"
    assert second_panel.headers["X-Cache"] == "HIT"
    assert oversized_panel.status_code == 422
    assert calls["panel"] == 1
    assert first_scan.headers["X-Cache"] == "MISS"
    assert second_scan.headers["X-Cache"] == "HIT"
    assert second_scan.json()["latency_ms"] == 0
    assert calls["scan"] == 1
