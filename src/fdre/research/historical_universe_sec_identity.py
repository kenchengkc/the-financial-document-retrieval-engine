"""SEC filing-level issuer→symbol corroboration for Historical Universe identities.

Ticker-state history can corroborate that a symbol occupied the index across an interval, but it
cannot bind that symbol to a particular SEC issuer.  This module supplies only that missing
issuer-binding layer from immutable SEC filing payloads.  It never changes membership dates or
identity boundaries.

A provisional identity is a promotion candidate only when:
- the existing pinned state-support planner fully contains the complete identity interval; and
- at least one SEC filing fetched under the exact issuer CIK explicitly reports the same
  ``dei:TradingSymbol``; and
- no inspected filing inside the interval reports a non-empty trading-symbol set that excludes
  the target symbol.

The planner is pure and projection-only.  Production mutation belongs in a separate, explicitly
guarded apply step after the evidence projection has been inspected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from fdre.research.historical_universe_lineage import normalize_symbol
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    StateSupportDecision,
)

SEC_IDENTITY_EVIDENCE_SCHEMA_VERSION = "fdre-hu-sec-trading-symbol-evidence-v1"
SEC_IDENTITY_DECISION_SCHEMA_VERSION = "fdre-hu-sec-identity-support-v1"
SecIdentitySupportStatus = Literal[
    "fully_supported",
    "state_not_fully_supported",
    "sec_symbol_missing",
    "sec_symbol_conflict",
]


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _concept_matches(value: str) -> bool:
    normalized = value.strip().casefold().replace("_", "")
    if normalized.startswith("{") and "}" in normalized:
        normalized = normalized.split("}", 1)[1]
    normalized = normalized.replace("-", "")
    return normalized == "tradingsymbol" or normalized.endswith(":tradingsymbol")


def _tag_concept(tag: Tag) -> str | None:
    explicit = tag.get("name")
    if isinstance(explicit, str) and _concept_matches(explicit):
        return explicit

    name = str(tag.name or "")
    prefix = getattr(tag, "prefix", None)
    qualified = f"{prefix}:{name}" if isinstance(prefix, str) and prefix else name
    if _concept_matches(qualified):
        return qualified
    return None


def extract_trading_symbols(content: str | bytes) -> tuple[tuple[str, str, str | None], ...]:
    """Extract only explicit XBRL/Inline-XBRL ``TradingSymbol`` facts.

    Returns ``(normalized_symbol, concept_name, context_ref)`` tuples.  Free-text cover-page
    labels are intentionally ignored; a value participates only when the payload itself marks it
    as the DEI trading-symbol concept.
    """

    soup = BeautifulSoup(content, "lxml")
    found: set[tuple[str, str, str | None]] = set()
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        concept = _tag_concept(tag)
        if concept is None:
            continue
        raw = " ".join(tag.get_text(" ", strip=True).split())
        if not raw:
            continue
        symbol = normalize_symbol(raw)
        if not symbol or len(symbol) > 32:
            continue
        context = tag.get("contextref") or tag.get("contextRef")
        context_ref = str(context).strip() if isinstance(context, str) and context.strip() else None
        found.add((symbol, concept, context_ref))
    return tuple(sorted(found))


def filing_directory_index_url(primary_document_url: str) -> str:
    """Return the immutable SEC filing-directory ``index.json`` URL."""

    parsed = urlsplit(primary_document_url)
    if parsed.scheme != "https" or parsed.netloc.casefold() != "www.sec.gov":
        raise ValueError("primary document must be an https://www.sec.gov URL")
    if "/Archives/edgar/data/" not in parsed.path:
        raise ValueError("primary document is not in the SEC EDGAR archive")
    directory = parsed.path.rsplit("/", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, f"{directory}/index.json", "", ""))


def xbrl_instance_filenames(index_payload: dict[str, object]) -> tuple[str, ...]:
    """Return deterministic candidate instance-document filenames from SEC directory JSON."""

    directory = index_payload.get("directory")
    if not isinstance(directory, dict):
        return ()
    items = directory.get("item")
    if not isinstance(items, list):
        return ()

    excluded_suffixes = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
    excluded_names = {"filingsummary.xml", "metalinks.json"}
    candidates: list[tuple[int, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        cleaned = name.strip()
        lowered = cleaned.casefold()
        if (
            not cleaned
            or "/" in cleaned
            or "\\" in cleaned
            or not lowered.endswith(".xml")
            or lowered in excluded_names
            or lowered.endswith(excluded_suffixes)
            or lowered.startswith("filingsummary")
            or lowered.startswith("r") and lowered[1:-4].isdigit()
        ):
            continue
        raw_size = item.get("size")
        try:
            size = int(raw_size) if raw_size is not None else 0
        except (TypeError, ValueError):
            size = 0
        candidates.append((size, cleaned))
    # Instance documents are normally the largest remaining XML after linkbase files are removed.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return tuple(name for _, name in candidates)


@dataclass(frozen=True, slots=True)
class SecTradingSymbolEvidence:
    row_id: int
    cik: str
    accession_number: str
    filing_date: date
    form_type: str
    symbol: str
    source_url: str
    payload_sha256: str
    concept_name: str
    context_ref: str | None = None

    def __post_init__(self) -> None:
        if self.row_id <= 0:
            raise ValueError("row_id must be positive")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be SHA-256")
        if not self.cik.isdigit() or len(self.cik) != 10:
            raise ValueError("cik must be a zero-padded 10-digit string")
        if self.symbol != normalize_symbol(self.symbol):
            raise ValueError("symbol must be normalized")
        if not _concept_matches(self.concept_name):
            raise ValueError("concept_name must identify TradingSymbol")

    @property
    def evidence_id(self) -> str:
        return _digest(
            {
                "schema_version": SEC_IDENTITY_EVIDENCE_SCHEMA_VERSION,
                "row_id": self.row_id,
                "cik": self.cik,
                "accession_number": self.accession_number,
                "filing_date": self.filing_date.isoformat(),
                "form_type": self.form_type,
                "symbol": self.symbol,
                "source_url": self.source_url,
                "payload_sha256": self.payload_sha256,
                "concept_name": self.concept_name,
                "context_ref": self.context_ref,
            }
        )

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["filing_date"] = self.filing_date.isoformat()
        payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class SecIdentityFilingObservation:
    row_id: int
    accession_number: str
    filing_date: date
    form_type: str
    symbols: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    inspected_urls: tuple[str, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.row_id <= 0:
            raise ValueError("row_id must be positive")
        if tuple(sorted(set(self.symbols))) != self.symbols:
            raise ValueError("symbols must be sorted and unique")
        if tuple(sorted(set(self.evidence_ids))) != self.evidence_ids:
            raise ValueError("evidence_ids must be sorted and unique")

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["filing_date"] = self.filing_date.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class SecIdentitySupportDecision:
    row_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    prior_source_hash: str
    status: SecIdentitySupportStatus
    state_decision_hash: str | None
    state_lineage_id: str | None
    sec_evidence_ids: tuple[str, ...]
    conflicting_accessions: tuple[str, ...]
    inspected_accessions: tuple[str, ...]
    reason: str
    decision_hash: str

    @property
    def promotion_candidate(self) -> bool:
        return self.status == "fully_supported"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["effective_from"] = self.effective_from.isoformat()
        payload["effective_to"] = self.effective_to.isoformat() if self.effective_to else None
        payload["promotion_candidate"] = self.promotion_candidate
        return payload


def plan_sec_identity_support(
    intervals: tuple[ProvisionalStateInterval, ...],
    state_decisions: tuple[StateSupportDecision, ...],
    observations: tuple[SecIdentityFilingObservation, ...],
) -> tuple[SecIdentitySupportDecision, ...]:
    """Combine full ticker-state containment with exact SEC CIK→symbol evidence."""

    states = {
        item.row_id: item
        for item in state_decisions
        if item.row_kind == "identity"
    }
    observations_by_row: dict[int, list[SecIdentityFilingObservation]] = {}
    for observation in observations:
        observations_by_row.setdefault(observation.row_id, []).append(observation)

    decisions: list[SecIdentitySupportDecision] = []
    seen: set[int] = set()
    for interval in sorted(intervals, key=lambda item: (item.effective_from, item.row_id)):
        if interval.row_kind != "identity":
            raise ValueError("SEC identity support accepts identity intervals only")
        if interval.row_id in seen:
            raise ValueError(f"duplicate provisional identity row {interval.row_id}")
        seen.add(interval.row_id)

        target = normalize_symbol(interval.symbol)
        state = states.get(interval.row_id)
        row_observations = sorted(
            observations_by_row.get(interval.row_id, []),
            key=lambda item: (item.filing_date, item.accession_number),
        )
        conflicts = tuple(
            item.accession_number
            for item in row_observations
            if item.symbols and target not in item.symbols
        )
        exact_evidence = tuple(
            sorted(
                {
                    evidence_id
                    for item in row_observations
                    if target in item.symbols
                    for evidence_id in item.evidence_ids
                }
            )
        )
        inspected_accessions = tuple(item.accession_number for item in row_observations)

        if state is None or state.status != "fully_supported" or state.lineage_id is None:
            status: SecIdentitySupportStatus = "state_not_fully_supported"
            reason = (
                "identity interval is not fully contained by exactly one pinned ticker-state "
                "lineage; SEC issuer binding cannot repair state/boundary ambiguity"
            )
        elif conflicts:
            status = "sec_symbol_conflict"
            reason = (
                "an inspected SEC filing under the same CIK reports trading symbols that exclude "
                "the target symbol inside the materialized identity interval"
            )
        elif not exact_evidence:
            status = "sec_symbol_missing"
            reason = (
                "no inspected SEC filing under the exact CIK explicitly reports the target "
                "dei:TradingSymbol"
            )
        else:
            status = "fully_supported"
            reason = (
                "one pinned ticker-state lineage fully contains the identity interval and an "
                "immutable SEC filing under the exact issuer CIK explicitly reports the same "
                "dei:TradingSymbol; no inspected filing conflicts"
            )

        decision_payload = {
            "schema_version": SEC_IDENTITY_DECISION_SCHEMA_VERSION,
            "row_id": interval.row_id,
            "security_id": interval.security_id,
            "cik": interval.cik,
            "symbol": target,
            "effective_from": interval.effective_from.isoformat(),
            "effective_to": interval.effective_to.isoformat() if interval.effective_to else None,
            "prior_source_hash": interval.source_hash,
            "status": status,
            "state_decision_hash": state.decision_hash if state is not None else None,
            "state_lineage_id": state.lineage_id if state is not None else None,
            "sec_evidence_ids": exact_evidence,
            "conflicting_accessions": conflicts,
            "inspected_accessions": inspected_accessions,
        }
        decisions.append(
            SecIdentitySupportDecision(
                row_id=interval.row_id,
                security_id=interval.security_id,
                cik=interval.cik,
                symbol=target,
                effective_from=interval.effective_from,
                effective_to=interval.effective_to,
                prior_source_hash=interval.source_hash,
                status=status,
                state_decision_hash=state.decision_hash if state is not None else None,
                state_lineage_id=state.lineage_id if state is not None else None,
                sec_evidence_ids=exact_evidence,
                conflicting_accessions=conflicts,
                inspected_accessions=inspected_accessions,
                reason=reason,
                decision_hash=_digest(decision_payload),
            )
        )
    return tuple(decisions)


def sec_identity_plan_id(decisions: tuple[SecIdentitySupportDecision, ...]) -> str:
    return _digest(
        {
            "schema_version": SEC_IDENTITY_DECISION_SCHEMA_VERSION,
            "decision_hashes": [item.decision_hash for item in decisions],
        }
    )
