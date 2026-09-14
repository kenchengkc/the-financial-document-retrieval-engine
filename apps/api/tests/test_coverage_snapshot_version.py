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
    document_count: int = 1,
    chunk_count: int = 1,
) -> CoverageResponse:
    tickers = indexed_tickers or ["AAPL"]
    return CoverageResponse(
        catalog_count=catalog_count,
        sp500_catalog_count=sp500_catalog_count,
        indexed_count=len(tickers),
        sp500_indexed_count=(
            len(tickers) if sp500_indexed_count is None else sp500_indexed_count
        ),
        document_count=document_count,
        chunk_count=chunk_count,
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


def test_get_coverage_rebinds_stale_catalog_without_rebuilding_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexed_tickers = ["AAPL", "MSFT", "NVDA", "EXMPL"]
    stale = _coverage(
        catalog_count=5,
        sp500_catalog_count=5,
        indexed_tickers=indexed_tickers,
        sp500_indexed_count=3,
        document_count=13_276,
        chunk_count=3_065_436,
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
    monkeypatch.setattr(
        companies_service,
        "sp500_primary_tickers",
        lambda: ["AAPL", "MSFT", "NVDA", "AMZN"],
    )
    monkeypatch.setattr(
        companies_service,
        "_build_coverage",
        lambda _session: pytest.fail("stale catalog metadata must not rescan corpus"),
    )
    monkeypatch.setattr(
        companies_service,
        "write_metric_snapshot",
        lambda _session, *, metric_key, payload: written.append(
            {"metric_key": metric_key, "payload": payload}
        ),
    )

    result = companies_service.get_coverage(session)

    assert result.catalog_count == 5_794
    assert result.sp500_catalog_count == 4
    assert result.indexed_tickers == ["AAPL", "MSFT", "NVDA"]
    assert result.indexed_count == 3
    assert result.sp500_indexed_count == 3
    assert result.document_count == 13_276
    assert result.chunk_count == 3_065_436
    assert len(written) == 1
    assert written[0]["payload"] == result.model_dump(mode="json")
    session.commit.assert_called_once()


def test_get_coverage_builds_corpus_snapshot_when_none_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _coverage(
        catalog_count=5_794,
        sp500_catalog_count=499,
        indexed_tickers=["AAPL", "MSFT"],
        sp500_indexed_count=2,
    )
    session = MagicMock()
    session.get_bind.return_value = object()
    written: list[dict[str, object]] = []

    companies_service.clear_coverage_cache()
    monkeypatch.setattr(
        companies_service,
        "read_metric_snapshot",
        lambda _session, _key: None,
    )
    monkeypatch.setattr(companies_service, "_build_coverage", lambda _session: built)
    monkeypatch.setattr(
        companies_service,
        "write_metric_snapshot",
        lambda _session, *, metric_key, payload: written.append(
            {"metric_key": metric_key, "payload": payload}
        ),
    )

    result = companies_service.get_coverage(session)

    assert result == built
    assert len(written) == 1
    session.commit.assert_called_once()
