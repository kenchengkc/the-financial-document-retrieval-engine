from __future__ import annotations

from unittest.mock import MagicMock

from apps.api.app.schemas.companies import CoverageResponse
from apps.api.app.services import companies_service


def _coverage(*, catalog_count: int, sp500_catalog_count: int) -> CoverageResponse:
    return CoverageResponse(
        catalog_count=catalog_count,
        sp500_catalog_count=sp500_catalog_count,
        indexed_count=1,
        sp500_indexed_count=1,
        document_count=1,
        chunk_count=1,
        indexed_tickers=["AAPL"],
    )


def test_static_catalog_change_invalidates_persisted_coverage(
    monkeypatch,
) -> None:
    monkeypatch.setattr(companies_service, "catalog_company_count", lambda: 5_794)
    monkeypatch.setattr(
        companies_service,
        "sp500_primary_tickers",
        lambda: ["AAPL", "MSFT"],
    )

    assert companies_service._coverage_snapshot_is_current(
        _coverage(catalog_count=5_794, sp500_catalog_count=2)
    )
    assert not companies_service._coverage_snapshot_is_current(
        _coverage(catalog_count=5_794, sp500_catalog_count=4)
    )


def test_get_coverage_rebuilds_stale_snapshot(monkeypatch) -> None:
    stale = _coverage(catalog_count=5_794, sp500_catalog_count=4)
    rebuilt = _coverage(catalog_count=5_794, sp500_catalog_count=499)
    session = MagicMock()
    session.get_bind.return_value = object()
    written: list[dict[str, object]] = []

    companies_service.clear_coverage_cache()
    monkeypatch.setattr(
        companies_service,
        "read_metric_snapshot",
        lambda _session, _key: stale.model_dump(mode="json"),
    )
    monkeypatch.setattr(companies_service, "catalog_company_count", lambda: 5_794)
    monkeypatch.setattr(
        companies_service,
        "sp500_primary_tickers",
        lambda: [f"T{index}" for index in range(499)],
    )
    monkeypatch.setattr(companies_service, "_build_coverage", lambda _session: rebuilt)
    monkeypatch.setattr(
        companies_service,
        "write_metric_snapshot",
        lambda _session, *, metric_key, payload: written.append(
            {"metric_key": metric_key, "payload": payload}
        ),
    )

    result = companies_service.get_coverage(session)

    assert result == rebuilt
    assert len(written) == 1
    assert written[0]["payload"] == rebuilt.model_dump(mode="json")
    session.commit.assert_called_once()
