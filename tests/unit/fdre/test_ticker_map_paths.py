from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdre.ingestion import ticker_map


def test_default_catalog_paths_resolve_checked_in_repository_data() -> None:
    assert ticker_map.LISTED_COMPANIES_PATH.is_file()
    assert ticker_map.SP500_TICKERS_PATH.is_file()

    payload = json.loads(ticker_map.SP500_TICKERS_PATH.read_text(encoding="utf-8"))
    primary_tickers = set(ticker_map.sp500_primary_tickers())

    assert len(primary_tickers) == payload["primary_ticker_count"]
    assert len(primary_tickers) > 400
    assert {"ARE", "MET", "AEP", "BX", "SO"}.issubset(primary_tickers)
    assert ticker_map.catalog_company_count() > 5_000


def test_configured_runtime_data_root_resolves_installed_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    listed = sample_dir / "listed_companies.json"
    sp500 = sample_dir / "sp500_tickers.json"
    listed.write_text("{}", encoding="utf-8")
    sp500.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("FDRE_DATA_ROOT", str(tmp_path))

    assert ticker_map._sample_data_path("listed_companies.json") == listed
    assert ticker_map._sample_data_path("sp500_tickers.json") == sp500
