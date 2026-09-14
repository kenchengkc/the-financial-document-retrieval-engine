from __future__ import annotations

from pathlib import Path

import pytest

from fdre.parsing.html_filing_parser import HTML_FILING_PARSER_VERSION, HtmlFilingParser
from fdre.parsing.sec_provenance import (
    SECParseProvenance,
    parse_sec_filing_bytes,
    parsed_elements_sha256,
    verify_sec_filing_replay,
)

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data/sample/sec_filing.html"


def test_exact_sec_bytes_replay_to_identical_parser_output() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    elements, provenance = parse_sec_filing_bytes(
        raw_bytes,
        source_url="https://www.sec.gov/example.htm",
    )

    replayed = verify_sec_filing_replay(raw_bytes, provenance)

    assert provenance.parser_version == HTML_FILING_PARSER_VERSION
    assert provenance.raw_size_bytes == len(raw_bytes)
    assert provenance.parsed_element_count == len(elements)
    assert provenance.parsed_elements_sha256 == parsed_elements_sha256(elements)
    assert [item.model_dump(mode="json") for item in replayed] == [
        item.model_dump(mode="json") for item in elements
    ]


def test_sec_parser_replay_rejects_tampered_raw_bytes() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    _, provenance = parse_sec_filing_bytes(raw_bytes)

    with pytest.raises(ValueError, match="raw SEC filing hash mismatch"):
        verify_sec_filing_replay(raw_bytes + b"<!-- tampered -->", provenance)


def test_sec_parser_replay_rejects_unavailable_parser_version() -> None:
    raw_bytes = FIXTURE_PATH.read_bytes()
    _, provenance = parse_sec_filing_bytes(raw_bytes)
    legacy = SECParseProvenance.model_validate(
        {
            **provenance.model_dump(mode="json"),
            "parser_version": "html-filing-parser-v0",
        }
    )

    with pytest.raises(ValueError, match="not replayable by this code"):
        verify_sec_filing_replay(raw_bytes, legacy)


def test_parser_output_digest_is_order_sensitive() -> None:
    elements = HtmlFilingParser().parse(FIXTURE_PATH.read_bytes())
    assert len(elements) > 1

    reversed_elements = list(reversed(elements))

    assert parsed_elements_sha256(elements) != parsed_elements_sha256(reversed_elements)
