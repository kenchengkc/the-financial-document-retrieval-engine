"""Exact ticker-interval lineage evidence for Historical Universe HU-2.

This module uses a pinned complete-history source to identify the exact S&P membership interval
whose boundary corresponds to one raw addition/removal observation. It then allows issuer CIK
evidence from SEC exact names, evidence-scoped HU2-R1 aliases, and present-day security identities
to corroborate that interval. No fuzzy symbol/name matching and no cross-interval propagation are
performed.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from fdre.research.historical_universe import SecurityIdentityRecord
from fdre.research.historical_universe_evidence import MembershipEvidence
from fdre.research.historical_universe_identity import (
    DerivedIssuerAliasEvidence,
    IssuerNameEvidence,
    SecCikNameIndex,
    derive_cross_source_issuer_aliases,
    normalize_cik,
    resolve_issuer_name,
)

LineageResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]

_LINEAGE_SCHEMA_VERSION = "fdre-hu2-ticker-membership-lineage-v1"
_LINEAGE_RESOLUTION_SCHEMA_VERSION = "fdre-hu2-ticker-lineage-resolution-v1"


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


@dataclass(frozen=True, slots=True)
class TickerMembershipLineage:
    """One continuous interval where a source ticker is present in the complete S&P history."""

    symbol: str
    effective_from: date
    effective_to: date | None
    source: str
    source_ref: str
    source_hash: str

    @property
    def lineage_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _LINEAGE_SCHEMA_VERSION,
                "symbol": self.symbol,
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "source": self.source,
                "source_ref": self.source_ref,
                "source_hash": self.source_hash,
            }
        )

    def matches_boundary(self, evidence: MembershipEvidence) -> bool:
        if normalize_symbol(evidence.raw_symbol) != self.symbol:
            return False
        if evidence.event_type == "addition":
            return evidence.effective_at == self.effective_from
        return self.effective_to is not None and evidence.effective_at == self.effective_to


@dataclass(frozen=True, slots=True)
class TickerLineageResolution:
    evidence_id: str
    status: LineageResolutionStatus
    lineage_id: str | None
    symbol: str
    cik: str | None
    candidate_ciks: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    supporting_sources: tuple[str, ...]
    resolution_hash: str
    reason: str | None = None


class TickerMembershipLineageAdapter:
    """Parse pinned ``sp500_ticker_start_end.csv`` from fja05680/sp500."""

    source_name = "fja05680/sp500-ticker-start-end"

    def __init__(self, *, source_ref: str) -> None:
        if not source_ref.strip():
            raise ValueError("source_ref is required")
        self.source_ref = source_ref.strip()

    def load(self, path: Path) -> tuple[TickerMembershipLineage, ...]:
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        rows: list[TickerMembershipLineage] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {
                "ticker",
                "start_date",
                "end_date",
            }.issubset(reader.fieldnames):
                raise ValueError("ticker lineage CSV must contain ticker,start_date,end_date")
            for row_number, row in enumerate(reader, start=2):
                raw_symbol = (row.get("ticker") or "").strip()
                raw_start = (row.get("start_date") or "").strip()
                raw_end = (row.get("end_date") or "").strip()
                if not raw_symbol or not raw_start:
                    raise ValueError(f"invalid ticker lineage row {row_number}")
                effective_from = date.fromisoformat(raw_start)
                effective_to = date.fromisoformat(raw_end) if raw_end else None
                if effective_to is not None and effective_to <= effective_from:
                    raise ValueError(f"non-positive ticker lineage interval on row {row_number}")
                rows.append(
                    TickerMembershipLineage(
                        symbol=normalize_symbol(raw_symbol),
                        effective_from=effective_from,
                        effective_to=effective_to,
                        source=self.source_name,
                        source_ref=self.source_ref,
                        source_hash=source_hash,
                    )
                )
        rows.sort(key=lambda item: (item.symbol, item.effective_from, item.lineage_id))
        return tuple(rows)


def _aliases_by_target(
    aliases: Sequence[DerivedIssuerAliasEvidence],
) -> dict[str, tuple[IssuerNameEvidence, ...]]:
    grouped: dict[str, list[IssuerNameEvidence]] = defaultdict(list)
    for alias in aliases:
        grouped[alias.target_evidence_id].append(alias.as_issuer_name_evidence())
    return {
        evidence_id: tuple(sorted(values, key=lambda item: item.evidence_id))
        for evidence_id, values in grouped.items()
    }


def _issuer_cik_for_evidence(
    record: MembershipEvidence,
    *,
    sec_index: SecCikNameIndex,
    aliases_by_target: dict[str, tuple[IssuerNameEvidence, ...]],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    direct = resolve_issuer_name(record.raw_name, sec_index)
    if direct.status == "resolved" and direct.cik is not None:
        return direct.cik, direct.evidence_ids, direct.evidence_sources
    if direct.status == "ambiguous":
        return None, direct.evidence_ids, direct.evidence_sources
    aliases = aliases_by_target.get(record.evidence_id, ())
    if not aliases:
        return None, (), ()
    resolution = resolve_issuer_name(record.raw_name, SecCikNameIndex(aliases))
    if resolution.status == "resolved" and resolution.cik is not None:
        return resolution.cik, resolution.evidence_ids, resolution.evidence_sources
    return None, resolution.evidence_ids, resolution.evidence_sources


def derive_lineage_cik_support(
    evidence: Sequence[MembershipEvidence],
    *,
    lineages: Sequence[TickerMembershipLineage],
    sec_index: SecCikNameIndex,
    current_identities: Sequence[SecurityIdentityRecord] = (),
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    """Return interval CIK, evidence-id, and source support maps.

    Present-day identity support is only attached to open intervals with an exact symbol match.
    Historical evidence support is only attached when one raw event exactly matches one interval
    boundary. Support is accumulated but never propagated between distinct ticker intervals.
    """

    aliases = derive_cross_source_issuer_aliases(evidence, sec_index=sec_index)
    alias_map = _aliases_by_target(aliases)
    by_symbol: dict[str, list[TickerMembershipLineage]] = defaultdict(list)
    for lineage in lineages:
        by_symbol[lineage.symbol].append(lineage)

    ciks_by_lineage: dict[str, set[str]] = defaultdict(set)
    evidence_ids_by_lineage: dict[str, set[str]] = defaultdict(set)
    sources_by_lineage: dict[str, set[str]] = defaultdict(set)

    for record in evidence:
        candidates = [
            lineage
            for lineage in by_symbol.get(normalize_symbol(record.raw_symbol), ())
            if lineage.matches_boundary(record)
        ]
        if len(candidates) != 1:
            continue
        cik, issuer_evidence_ids, issuer_sources = _issuer_cik_for_evidence(
            record,
            sec_index=sec_index,
            aliases_by_target=alias_map,
        )
        if cik is None:
            continue
        lineage_id = candidates[0].lineage_id
        ciks_by_lineage[lineage_id].add(normalize_cik(cik))
        evidence_ids_by_lineage[lineage_id].add(record.evidence_id)
        evidence_ids_by_lineage[lineage_id].update(issuer_evidence_ids)
        sources_by_lineage[lineage_id].add(record.source.strip())
        sources_by_lineage[lineage_id].update(issuer_sources)

    active_current_by_symbol: dict[str, list[SecurityIdentityRecord]] = defaultdict(list)
    for identity in current_identities:
        if identity.verification_status == "rejected" or identity.effective_to is not None:
            continue
        active_current_by_symbol[normalize_symbol(identity.symbol)].append(identity)
    for lineage in lineages:
        if lineage.effective_to is not None:
            continue
        matches = active_current_by_symbol.get(lineage.symbol, ())
        security_ids = {identity.security_id for identity in matches}
        ciks = {normalize_cik(identity.cik) for identity in matches}
        if len(security_ids) != 1 or len(ciks) != 1:
            continue
        lineage_id = lineage.lineage_id
        ciks_by_lineage[lineage_id].update(ciks)
        sources_by_lineage[lineage_id].add("fdre-current-security-identity")
        evidence_ids_by_lineage[lineage_id].update(identity.source_hash for identity in matches)

    return (
        {key: tuple(sorted(values)) for key, values in ciks_by_lineage.items()},
        {key: tuple(sorted(values)) for key, values in evidence_ids_by_lineage.items()},
        {key: tuple(sorted(values)) for key, values in sources_by_lineage.items()},
    )


def resolve_evidence_via_ticker_lineage(
    evidence: Sequence[MembershipEvidence],
    *,
    lineages: Sequence[TickerMembershipLineage],
    sec_index: SecCikNameIndex,
    current_identities: Sequence[SecurityIdentityRecord] = (),
) -> tuple[TickerLineageResolution, ...]:
    """Resolve evidence to a unique ticker interval and interval-backed CIK, fail-closed."""

    cik_support, evidence_support, source_support = derive_lineage_cik_support(
        evidence,
        lineages=lineages,
        sec_index=sec_index,
        current_identities=current_identities,
    )
    by_symbol: dict[str, list[TickerMembershipLineage]] = defaultdict(list)
    for lineage in lineages:
        by_symbol[lineage.symbol].append(lineage)

    results: list[TickerLineageResolution] = []
    for record in sorted(evidence, key=lambda item: item.evidence_id):
        symbol = normalize_symbol(record.raw_symbol)
        candidates = [
            lineage
            for lineage in by_symbol.get(symbol, ())
            if lineage.matches_boundary(record)
        ]
        if len(candidates) != 1:
            status: LineageResolutionStatus = "ambiguous" if len(candidates) > 1 else "unresolved"
            reason: str | None = (
                "multiple complete-history ticker intervals match the raw event boundary"
                if len(candidates) > 1
                else "no exact complete-history ticker interval boundary match"
            )
            resolution_hash = _sha256_json(
                {
                    "schema_version": _LINEAGE_RESOLUTION_SCHEMA_VERSION,
                    "evidence_id": record.evidence_id,
                    "status": status,
                    "candidate_lineage_ids": sorted(item.lineage_id for item in candidates),
                }
            )
            results.append(
                TickerLineageResolution(
                    evidence_id=record.evidence_id,
                    status=status,
                    lineage_id=None,
                    symbol=symbol,
                    cik=None,
                    candidate_ciks=(),
                    supporting_evidence_ids=(),
                    supporting_sources=(),
                    resolution_hash=resolution_hash,
                    reason=reason,
                )
            )
            continue

        lineage = candidates[0]
        ciks = cik_support.get(lineage.lineage_id, ())
        cik: str | None
        reason: str | None
        if len(ciks) == 1:
            status = "resolved"
            cik = ciks[0]
            reason = None
        elif len(ciks) > 1:
            status = "ambiguous"
            cik = None
            reason = "ticker interval has conflicting issuer CIK support"
        else:
            status = "unresolved"
            cik = None
            reason = "ticker interval has no issuer CIK support"
        support_ids = evidence_support.get(lineage.lineage_id, ())
        support_sources = source_support.get(lineage.lineage_id, ())
        resolution_hash = _sha256_json(
            {
                "schema_version": _LINEAGE_RESOLUTION_SCHEMA_VERSION,
                "evidence_id": record.evidence_id,
                "lineage_id": lineage.lineage_id,
                "status": status,
                "candidate_ciks": list(ciks),
                "supporting_evidence_ids": list(support_ids),
                "supporting_sources": list(support_sources),
            }
        )
        results.append(
            TickerLineageResolution(
                evidence_id=record.evidence_id,
                status=status,
                lineage_id=lineage.lineage_id,
                symbol=symbol,
                cik=cik,
                candidate_ciks=ciks,
                supporting_evidence_ids=support_ids,
                supporting_sources=support_sources,
                resolution_hash=resolution_hash,
                reason=reason,
            )
        )
    return tuple(results)
