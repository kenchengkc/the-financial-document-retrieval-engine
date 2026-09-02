from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.api.app.schemas.companies import CoverageResponse
from apps.api.app.services import companies_service


def _coverage(
    *,
    catalog_count: int,
    sp500_catalog_count: int,
    indexed_tickers: list[str] | None = None,
    sp500_indexed_count: int | None = None,
) -> CoverageResponse:
    tickers = indexed_tickers or ["AAPL"]
    return CoverageResponse(
        catalog_count=catalog_count,
        sp500_catalog_count=sp500_catalog_count,
        indexed_count=len(tickers),
        sp500_indexed_count=(
            len(tickers) if sp500_indexed_count is None else sp500_indexed_count
        ),
        document_count=1,
        chunk_count=1,
        indexed_tickers=tickers,
    )


def test_static_catalog_change_invalidates_persisted_coverage(
    monkeypatch: pytest.MonkeyPatch,
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


def test_derived_sp500_count_mismatch_invalidates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companies_service, "catalog_company_count", lambda: 5_794)
    monkeypatch.setattr(
        companies_service,
        "sp500_primary_tickers",
        lambda: ["AAPL", "MSFT"],
    )

    stale = _coverage(
        catalog_count=5_794,
        sp500_catalog_count=2,
        indexed_tickers=["AAPL", "MSFT"],
        sp500_indexed_count=1,
    )

    assert not companies_service._coverage_snapshot_is_current(stale)


def test_get_coverage_rebuilds_stale_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tickers = [f"T{index}" for index in range(499)]
    stale = _coverage(
        catalog_count=5_794,
        sp500_catalog_count=499,
        indexed_tickers=tickers,
        sp500_indexed_count=4,
    )
    rebuilt = _coverage(
        catalog_count=5_794,
        sp500_catalog_count=499,
        indexed_tickers=tickers,
        sp500_indexed_count=499,
    )
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
    monkeypatch.setattr(companies_service, "sp500_primary_tickers", lambda: tickers)
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
