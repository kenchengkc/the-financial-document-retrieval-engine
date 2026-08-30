from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.historical_universe_coverage import _sha256_file, _source_manifest


def test_source_manifest_records_hashes_and_pins(tmp_path: Path) -> None:
    observed_at = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)
    snp = tmp_path / "history.csv"
    wiki = tmp_path / "wiki.html"
    sec = tmp_path / "cik.txt"
    snp.write_text("snp\n", encoding="utf-8")
    wiki.write_text("wiki\n", encoding="utf-8")
    sec.write_text("sec\n", encoding="utf-8")

    manifest = _source_manifest(
        observed_at=observed_at,
        snp_history=snp,
        wikipedia_html=wiki,
        sec_cik_lookup=sec,
        snp_history_ref="abc123",
        wikipedia_revision="1234567890",
    )

    sources = cast(dict[str, dict[str, object]], manifest["sources"])
    assert sources["snp_history"]["sha256"] == _sha256_file(snp)
    assert sources["snp_history"]["git_ref"] == "abc123"
    assert sources["wikipedia_sp500_component_changes"]["revision"] == "1234567890"
    assert sources["sec_cik_lookup"]["sha256"] == _sha256_file(sec)
    assert manifest["observed_at"] == observed_at.isoformat()


def test_sha256_file_is_content_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first", encoding="utf-8")
    first = _sha256_file(path)
    path.write_text("second", encoding="utf-8")
    second = _sha256_file(path)
    assert first != second
