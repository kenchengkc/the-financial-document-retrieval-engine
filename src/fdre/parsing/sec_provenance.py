"""Content-addressed provenance and offline replay for parsed SEC filing HTML."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fdre.parsing.base import ParsedElement
from fdre.parsing.html_filing_parser import (
    HTML_FILING_PARSER_NAME,
    HTML_FILING_PARSER_VERSION,
    HtmlFilingParser,
)

SEC_PARSE_PROVENANCE_KEY = "sec_parse_provenance"
SEC_PARSE_PROVENANCE_VERSION: Literal["sec-parse-provenance-v1"] = (
    "sec-parse-provenance-v1"
)


class SECParseProvenance(BaseModel):
    """Immutable identity binding one parsed element set to exact source bytes."""

    model_config = ConfigDict(frozen=True)

    provenance_version: Literal["sec-parse-provenance-v1"] = SEC_PARSE_PROVENANCE_VERSION
    parser_name: str = HTML_FILING_PARSER_NAME
    parser_version: str = HTML_FILING_PARSER_VERSION
    raw_sha256: str = Field(min_length=64, max_length=64)
    raw_size_bytes: int = Field(ge=0)
    parsed_elements_sha256: str = Field(min_length=64, max_length=64)
    parsed_element_count: int = Field(ge=0)
    source_url: str | None = None


def parse_sec_filing_bytes(
    content: bytes,
    *,
    source_url: str | None = None,
    expected_sha256: str | None = None,
    parser: HtmlFilingParser | None = None,
) -> tuple[list[ParsedElement], SECParseProvenance]:
    """Hash and parse the same immutable byte string, then bind the outputs together."""

    raw_sha256 = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and raw_sha256 != expected_sha256:
        raise ValueError(
            "raw SEC filing hash mismatch: "
            f"expected {expected_sha256}, got {raw_sha256}"
        )
    active_parser = parser or HtmlFilingParser()
    if active_parser.parser_name != HTML_FILING_PARSER_NAME:
        raise ValueError(f"unsupported SEC parser {active_parser.parser_name!r}")
    if active_parser.parser_version != HTML_FILING_PARSER_VERSION:
        raise ValueError(
            "SEC parser version mismatch: "
            f"expected {HTML_FILING_PARSER_VERSION}, got {active_parser.parser_version}"
        )
    elements = active_parser.parse(content)
    provenance = SECParseProvenance(
        raw_sha256=raw_sha256,
        raw_size_bytes=len(content),
        parsed_elements_sha256=parsed_elements_sha256(elements),
        parsed_element_count=len(elements),
        source_url=source_url,
    )
    return elements, provenance


def verify_sec_filing_replay(
    content: bytes,
    provenance: SECParseProvenance,
    *,
    parser: HtmlFilingParser | None = None,
) -> list[ParsedElement]:
    """Re-run parsing from exact raw bytes and fail closed on any identity mismatch."""

    if provenance.provenance_version != SEC_PARSE_PROVENANCE_VERSION:
        raise ValueError(
            f"unsupported SEC parse provenance version {provenance.provenance_version!r}"
        )
    if provenance.parser_name != HTML_FILING_PARSER_NAME:
        raise ValueError(f"unsupported SEC parser {provenance.parser_name!r}")
    if provenance.parser_version != HTML_FILING_PARSER_VERSION:
        raise ValueError(
            "SEC parser version is not replayable by this code: "
            f"{provenance.parser_version}"
        )
    elements, replayed = parse_sec_filing_bytes(
        content,
        source_url=provenance.source_url,
        expected_sha256=provenance.raw_sha256,
        parser=parser,
    )
    if replayed.raw_size_bytes != provenance.raw_size_bytes:
        raise ValueError("raw SEC filing size mismatch")
    if replayed.parsed_element_count != provenance.parsed_element_count:
        raise ValueError("SEC parser replay element-count mismatch")
    if replayed.parsed_elements_sha256 != provenance.parsed_elements_sha256:
        raise ValueError("SEC parser replay element digest mismatch")
    return elements


def parsed_elements_sha256(elements: list[ParsedElement]) -> str:
    """Return the canonical digest of ordered parser output, excluding database ids."""

    return _stable_digest([element.model_dump(mode="json") for element in elements])


def parse_provenance_from_metadata(metadata: dict[str, Any] | None) -> SECParseProvenance | None:
    if not metadata:
        return None
    payload = metadata.get(SEC_PARSE_PROVENANCE_KEY)
    if payload is None:
        return None
    return SECParseProvenance.model_validate(payload)


def metadata_with_parse_provenance(
    metadata: dict[str, Any] | None,
    provenance: SECParseProvenance,
) -> dict[str, Any]:
    updated = dict(metadata or {})
    updated[SEC_PARSE_PROVENANCE_KEY] = provenance.model_dump(mode="json")
    return updated


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
