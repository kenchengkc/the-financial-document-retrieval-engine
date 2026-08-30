from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from scripts.historical_universe_coverage import (
    _current_constituent_reconciliation,
    _raw_evidence_diagnostics,
    _sha256_file,
    _source_manifest,
)

from fdre.research.historical_universe_evidence import (
    MembershipEventType,
    MembershipEvidence,
)


def test_source_manifest_records_hashes_and_pins(tmp_path: Path) -> None:
    observed_at = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)
    snp = tmp_path / "history.csv"
    wiki = tmp_path / "wiki.html"
    sec = tmp_path / "cik.txt"
    current = tmp_path / "current.json"
    snp.write_text("snp\n", encoding="utf-8")
    wiki.write_text("wiki\n", encoding="utf-8")
    sec.write_text("sec\n", encoding="utf-8")
    current.write_text("{}\n", encoding="utf-8")

    manifest = _source_manifest(
        observed_at=observed_at,
        snp_history=snp,
        wikipedia_html=wiki,
        sec_cik_lookup=sec,
        current_constituents=current,
        snp_history_ref="abc123",
        wikipedia_revision="1234567890",
    )

    sources = cast(dict[str, dict[str, object]], manifest["sources"])
    assert sources["snp_history"]["sha256"] == _sha256_file(snp)
    assert sources["snp_history"]["git_ref"] == "abc123"
    wikipedia = sources["wikipedia_historical_components"]
    assert wikipedia["revision"] == "1234567890"
    assert wikipedia["title"] == "Historical components of the S&P 500"
    assert sources["sec_cik_lookup"]["sha256"] == _sha256_file(sec)
    current_source = sources["current_constituents_check"]
    assert current_source["sha256"] == _sha256_file(current)
    assert current_source["role"] == "present-day reconciliation check only"
    assert manifest["observed_at"] == observed_at.isoformat()


def test_sha256_file_is_content_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("first", encoding="utf-8")
    first = _sha256_file(path)
    path.write_text("second", encoding="utf-8")
    second = _sha256_file(path)
    assert first != second


def test_current_constituent_reconciliation_keeps_share_classes_distinct(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sp500.json"
    path.write_text(
        json.dumps(
            {
                "source": "test",
                "generated_at": "2026-06-08T13:50:33+00:00",
                "constituent_count": 4,
                "primary_ticker_count": 2,
                "missing_from_catalog": ["CBOE"],
                "aliases": {"GOOG": "GOOG", "GOOGL": "GOOG", "MSFT": "MSFT"},
                "primary_tickers": ["GOOG", "MSFT"],
            }
        ),
        encoding="utf-8",
    )

    report = _current_constituent_reconciliation(
        path,
        production_tickers=("MSFT", "GOOG"),
        identities=(),
    )

    assert report["constituent_symbol_count"] == 4
    assert report["primary_ticker_count"] == 2
    assert report["mapped_production_seed_exact_match"] is True
    assert report["missing_catalog_symbols"] == ["CBOE"]
    assert report["unique_active_security_identity_count"] == 0
    assert report["missing_active_security_identity_symbols"] == [
        "CBOE",
        "GOOG",
        "GOOGL",
        "MSFT",
    ]
    assert report["current_security_identity_complete"] is False


def test_raw_evidence_diagnostics_separates_agreement_from_opposing_events() -> None:
    observed_at = datetime(2026, 8, 30, tzinfo=UTC)

    def evidence(event_type: str, source: str, raw_name: str) -> MembershipEvidence:
        return MembershipEvidence(
            universe_code="sp500",
            event_type=cast(MembershipEventType, event_type),
            effective_at=observed_at.date(),
            raw_symbol="ABC",
            raw_name=raw_name,
            source=source,
            source_observed_at=observed_at,
            source_record_hash="a" * 64,
        )

    report = _raw_evidence_diagnostics(
        (
            evidence("addition", "source-a", "New Co"),
            evidence("addition", "source-b", "New Co"),
            evidence("removal", "source-a", "Old Co"),
        )
    )

    assert report["exact_cross_source_agreement_key_count"] == 1
    assert report["exact_cross_source_agreement_evidence_count"] == 2
    assert report["same_date_symbol_opposing_event_key_count"] == 1
