"""Historical issuer-name evidence for Historical Universe v1 / HU-2.

This module deliberately keeps SEC issuer identity separate from listed-security identity.
The SEC CIK lookup is historically cumulative for company names and CIKs are not recycled,
which makes it useful as exact issuer-name evidence. It is not a historical ticker feed and
never fabricates a security identity period.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import Security
from fdre.research.historical_universe import SecurityIdentityRecord
from fdre.research.historical_universe_evidence import (
    IdentityResolution,
    MembershipEvidence,
    resolve_membership_evidence,
)

IssuerResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]

_SEC_CIK_LOOKUP_SOURCE = "sec-edgar-cik-lookup"
_SEC_CIK_LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
_CROSS_SOURCE_ALIAS_SOURCE = "fdre-cross-source-membership-alias"
_CROSS_SOURCE_ALIAS_URL = "fdre://historical-universe/cross-source-membership-alias"
_ISSUER_EVIDENCE_SCHEMA_VERSION = "fdre-hu-issuer-name-evidence-v1"
_ISSUER_RESOLUTION_SCHEMA_VERSION = "fdre-hu-issuer-name-resolution-v2"
_DERIVED_ALIAS_SCHEMA_VERSION = "fdre-hu2-cross-source-issuer-alias-v1"


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_issuer_name(value: str) -> str:
    """Normalize punctuation/case only; intentionally avoid fuzzy legal-name inference."""

    words = "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()
    return " ".join(words)


def normalize_cik(value: str) -> str:
    stripped = value.strip()
    if not stripped.isdigit():
        raise ValueError(f"CIK must be numeric: {value!r}")
    if len(stripped) > 10:
        raise ValueError(f"CIK must be at most 10 digits: {value!r}")
    return stripped.zfill(10)


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


@dataclass(frozen=True, slots=True)
class IssuerNameEvidence:
    """One exact name-to-CIK association from a pinned or derived evidence source."""

    cik: str
    raw_name: str
    normalized_name: str
    source_record_hash: str
    source_observed_at: datetime
    source: str = _SEC_CIK_LOOKUP_SOURCE
    source_url: str = _SEC_CIK_LOOKUP_URL

    def __post_init__(self) -> None:
        if not self.raw_name.strip():
            raise ValueError("raw_name is required")
        if not self.normalized_name:
            raise ValueError("normalized_name is required")
        if self.cik != normalize_cik(self.cik):
            raise ValueError("cik must be zero-padded to 10 digits")
        if self.source_observed_at.tzinfo is None or self.source_observed_at.utcoffset() is None:
            raise ValueError("source_observed_at must be timezone-aware")
        if len(self.source_record_hash) != 64:
            raise ValueError("source_record_hash must be SHA-256")

    @property
    def evidence_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _ISSUER_EVIDENCE_SCHEMA_VERSION,
                "cik": self.cik,
                "normalized_name": self.normalized_name,
                "source_record_hash": self.source_record_hash,
                "source": self.source,
            }
        )


@dataclass(frozen=True, slots=True)
class DerivedIssuerAliasEvidence:
    """Issuer alias inferred only from an exact event shared by independent sources.

    One source must provide a raw issuer name that resolves exactly through the SEC cumulative
    CIK lookup. A different source may then contribute a second raw issuer name for the exact
    same universe/date/event-type/symbol key. No fuzzy string similarity or transitive alias
    chaining participates in this derivation.
    """

    cik: str
    raw_name: str
    normalized_name: str
    universe_code: str
    effective_at: date
    event_type: str
    raw_symbol: str
    target_evidence_id: str
    supporting_evidence_ids: tuple[str, ...]
    supporting_sources: tuple[str, ...]
    supporting_raw_names: tuple[str, ...]
    source_observed_at: datetime
    source: str = _CROSS_SOURCE_ALIAS_SOURCE
    source_url: str = _CROSS_SOURCE_ALIAS_URL

    def __post_init__(self) -> None:
        if self.cik != normalize_cik(self.cik):
            raise ValueError("cik must be zero-padded to 10 digits")
        if not self.raw_name.strip() or not self.normalized_name:
            raise ValueError("alias name is required")
        if not self.supporting_evidence_ids:
            raise ValueError("cross-source alias requires supporting evidence")
        if not self.supporting_sources:
            raise ValueError("cross-source alias requires a supporting source")
        if self.source_observed_at.tzinfo is None or self.source_observed_at.utcoffset() is None:
            raise ValueError("source_observed_at must be timezone-aware")

    @property
    def alias_id(self) -> str:
        return _sha256_json(
            {
                "schema_version": _DERIVED_ALIAS_SCHEMA_VERSION,
                "cik": self.cik,
                "normalized_name": self.normalized_name,
                "universe_code": self.universe_code,
                "effective_at": self.effective_at.isoformat(),
                "event_type": self.event_type,
                "raw_symbol": self.raw_symbol,
                "target_evidence_id": self.target_evidence_id,
                "supporting_evidence_ids": list(self.supporting_evidence_ids),
            }
        )

    def as_issuer_name_evidence(self) -> IssuerNameEvidence:
        return IssuerNameEvidence(
            cik=self.cik,
            raw_name=self.raw_name,
            normalized_name=self.normalized_name,
            source_record_hash=self.alias_id,
            source_observed_at=self.source_observed_at,
            source=self.source,
            source_url=self.source_url,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "alias_id": self.alias_id,
            "cik": self.cik,
            "raw_name": self.raw_name,
            "normalized_name": self.normalized_name,
            "universe_code": self.universe_code,
            "effective_at": self.effective_at.isoformat(),
            "event_type": self.event_type,
            "raw_symbol": self.raw_symbol,
            "target_evidence_id": self.target_evidence_id,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "supporting_sources": list(self.supporting_sources),
            "supporting_raw_names": list(self.supporting_raw_names),
            "source_observed_at": self.source_observed_at.isoformat(),
            "source": self.source,
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class IssuerNameResolution:
    """Exact historical issuer-name resolution result."""

    raw_name: str | None
    normalized_name: str | None
    status: IssuerResolutionStatus
    cik: str | None
    candidate_ciks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_sources: tuple[str, ...]
    resolution_hash: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StableSecurityRecord:
    """Stable listed security keyed to an SEC issuer/CIK."""

    security_id: int
    cik: str
    security_type: str = "common_stock"
    share_class: str | None = None

    def __post_init__(self) -> None:
        if self.security_id <= 0:
            raise ValueError("security_id must be positive")
        if self.cik != normalize_cik(self.cik):
            raise ValueError("cik must be zero-padded to 10 digits")


class SecCikNameIndex:
    """Compact exact-name index over source-backed issuer-name evidence."""

    def __init__(self, records: Sequence[IssuerNameEvidence]) -> None:
        by_name: dict[str, list[IssuerNameEvidence]] = defaultdict(list)
        for record in records:
            by_name[record.normalized_name].append(record)
        self._by_name = {
            name: tuple(sorted(items, key=lambda item: (item.cik, item.evidence_id)))
            for name, items in by_name.items()
        }

    def lookup(self, raw_name: str | None) -> tuple[IssuerNameEvidence, ...]:
        if raw_name is None:
            return ()
        normalized = normalize_issuer_name(raw_name)
        if not normalized:
            return ()
        return self._by_name.get(normalized, ())

    @property
    def name_count(self) -> int:
        return len(self._by_name)


class SecCikLookupAdapter:
    """Parse a local copy of SEC ``cik-lookup-data.txt``.

    No network request is performed. The SEC file is large but line-oriented, so callers can
    optionally restrict ingestion to normalized names actually observed in membership evidence.
    """

    source_name = _SEC_CIK_LOOKUP_SOURCE
    source_url = _SEC_CIK_LOOKUP_URL

    @staticmethod
    def parse_line(line: str, *, observed_at: datetime) -> IssuerNameEvidence | None:
        text = line.rstrip("\r\n")
        if not text.strip():
            return None
        try:
            raw_name, cik, trailing = text.rsplit(":", 2)
        except ValueError as exc:
            raise ValueError(f"invalid SEC CIK lookup line: {text!r}") from exc
        if trailing:
            raise ValueError(f"unexpected trailing SEC CIK lookup field: {text!r}")
        normalized_name = normalize_issuer_name(raw_name)
        if not normalized_name:
            # The cumulative SEC file currently contains a small number of CIK-only
            # rows (for example ``:0001003197:``). They provide no issuer-name
            # evidence and therefore cannot participate in exact name resolution.
            return None
        return IssuerNameEvidence(
            cik=normalize_cik(cik),
            raw_name=raw_name.strip(),
            normalized_name=normalized_name,
            source_record_hash=hashlib.sha256(
                text.encode("latin-1", errors="replace")
            ).hexdigest(),
            source_observed_at=observed_at,
        )

    def load(
        self,
        path: Path,
        *,
        observed_at: datetime,
        restrict_to_names: Iterable[str] | None = None,
    ) -> tuple[IssuerNameEvidence, ...]:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        wanted = (
            {normalize_issuer_name(name) for name in restrict_to_names}
            if restrict_to_names is not None
            else None
        )
        if wanted is not None:
            wanted.discard("")

        records: list[IssuerNameEvidence] = []
        with path.open("r", encoding="latin-1", errors="replace") as handle:
            for line in handle:
                record = self.parse_line(line, observed_at=observed_at)
                if record is None:
                    continue
                if wanted is not None and record.normalized_name not in wanted:
                    continue
                records.append(record)
        records.sort(key=lambda item: (item.normalized_name, item.cik, item.evidence_id))
        return tuple(records)


def resolve_issuer_name(raw_name: str | None, index: SecCikNameIndex) -> IssuerNameResolution:
    normalized = normalize_issuer_name(raw_name or "") or None
    matches = index.lookup(raw_name)
    ciks = tuple(sorted({record.cik for record in matches}))
    evidence_ids = tuple(sorted(record.evidence_id for record in matches))
    evidence_sources = tuple(sorted({record.source for record in matches}))
    status: IssuerResolutionStatus
    if len(ciks) == 1:
        status = "resolved"
        cik = ciks[0]
        reason = None
    elif len(ciks) > 1:
        status = "ambiguous"
        cik = None
        reason = "exact normalized SEC name maps to multiple CIKs"
    else:
        status = "unresolved"
        cik = None
        reason = "no exact normalized SEC historical name match"
    resolution_hash = _sha256_json(
        {
            "schema_version": _ISSUER_RESOLUTION_SCHEMA_VERSION,
            "normalized_name": normalized,
            "status": status,
            "candidate_ciks": ciks,
            "evidence_ids": evidence_ids,
            "evidence_sources": evidence_sources,
        }
    )
    return IssuerNameResolution(
        raw_name=raw_name,
        normalized_name=normalized,
        status=status,
        cik=cik,
        candidate_ciks=ciks,
        evidence_ids=evidence_ids,
        evidence_sources=evidence_sources,
        resolution_hash=resolution_hash,
        reason=reason,
    )


def derive_cross_source_issuer_aliases(
    evidence: Sequence[MembershipEvidence],
    *,
    sec_index: SecCikNameIndex,
) -> tuple[DerivedIssuerAliasEvidence, ...]:
    """Derive fail-closed issuer aliases from exact cross-source membership-event agreement.

    The SEC-only index is intentionally passed separately and is the sole identity authority for
    supporting names. Derived aliases are never fed back into this derivation, preventing
    transitive alias chains. A group is eligible only when at least two independent source names
    describe the exact same universe/date/event-type/symbol key and all SEC-resolved support
    points to one CIK. If the same normalized alias is independently derived to different CIKs,
    every derivation for that alias is discarded rather than converted into a guess.
    """

    by_event: dict[tuple[str, date, str, str], list[MembershipEvidence]] = defaultdict(list)
    for record in evidence:
        key = (
            record.universe_code.strip().lower(),
            record.effective_at,
            record.event_type,
            _normalize_symbol(record.raw_symbol),
        )
        by_event[key].append(record)

    aliases: list[DerivedIssuerAliasEvidence] = []
    for (universe_code, effective_at, event_type, symbol), records in sorted(
        by_event.items(), key=lambda item: item[0]
    ):
        if len({record.source for record in records}) < 2:
            continue

        resolved_support: list[tuple[MembershipEvidence, str]] = []
        resolutions: dict[str, IssuerNameResolution] = {}
        for record in records:
            resolution = resolve_issuer_name(record.raw_name, sec_index)
            resolutions[record.evidence_id] = resolution
            if resolution.status == "resolved" and resolution.cik is not None:
                resolved_support.append((record, resolution.cik))
        supported_ciks = {cik for _, cik in resolved_support}
        if len(supported_ciks) != 1:
            continue
        cik = next(iter(supported_ciks))

        for target in records:
            target_resolution = resolutions[target.evidence_id]
            if target_resolution.status != "unresolved" or target.raw_name is None:
                continue
            normalized_name = normalize_issuer_name(target.raw_name)
            if not normalized_name:
                continue
            supporting_records = tuple(
                sorted(
                    (
                        support
                        for support, support_cik in resolved_support
                        if support_cik == cik and support.source != target.source
                    ),
                    key=lambda item: (item.source, item.evidence_id),
                )
            )
            if not supporting_records:
                continue
            aliases.append(
                DerivedIssuerAliasEvidence(
                    cik=cik,
                    raw_name=target.raw_name.strip(),
                    normalized_name=normalized_name,
                    universe_code=universe_code,
                    effective_at=effective_at,
                    event_type=event_type,
                    raw_symbol=symbol,
                    target_evidence_id=target.evidence_id,
                    supporting_evidence_ids=tuple(
                        record.evidence_id for record in supporting_records
                    ),
                    supporting_sources=tuple(
                        sorted({record.source for record in supporting_records})
                    ),
                    supporting_raw_names=tuple(
                        sorted(
                            {
                                record.raw_name.strip()
                                for record in supporting_records
                                if record.raw_name is not None and record.raw_name.strip()
                            }
                        )
                    ),
                    source_observed_at=max(
                        record.source_observed_at for record in (target, *supporting_records)
                    ),
                )
            )

    ciks_by_alias: dict[str, set[str]] = defaultdict(set)
    for alias in aliases:
        ciks_by_alias[alias.normalized_name].add(alias.cik)
    conflicting_names = {
        normalized_name
        for normalized_name, ciks in ciks_by_alias.items()
        if len(ciks) > 1
    }
    return tuple(
        sorted(
            (alias for alias in aliases if alias.normalized_name not in conflicting_names),
            key=lambda item: (
                item.normalized_name,
                item.cik,
                item.effective_at,
                item.event_type,
                item.raw_symbol,
                item.target_evidence_id,
            ),
        )
    )


def issuer_resolution_uses_cross_source_alias(resolution: IssuerNameResolution | None) -> bool:
    return resolution is not None and _CROSS_SOURCE_ALIAS_SOURCE in resolution.evidence_sources


def resolve_membership_with_sec_issuer_fallback(
    evidence: MembershipEvidence,
    *,
    identities: Sequence[SecurityIdentityRecord],
    issuer_index: SecCikNameIndex,
    securities: Sequence[StableSecurityRecord],
) -> tuple[IdentityResolution, IssuerNameResolution | None]:
    """Resolve membership evidence without inventing historical ticker periods.

    Existing HU-1 date-aware ticker/CIK identity periods always get first priority. Only when
    they return ``unresolved`` do we attempt exact source-backed historical-name resolution. A
    unique CIK can resolve to a stable security only when exactly one listed security exists for
    that CIK; multiple share classes fail closed as ambiguous.
    """

    primary = resolve_membership_evidence(evidence, identities)
    if primary.status != "unresolved":
        return primary, None

    issuer = resolve_issuer_name(evidence.raw_name, issuer_index)
    if issuer.status != "resolved" or issuer.cik is None:
        return (
            IdentityResolution(
                evidence_id=evidence.evidence_id,
                status="ambiguous" if issuer.status == "ambiguous" else "unresolved",
                method="unresolved",
                confidence=0.0,
                reason=issuer.reason,
            ),
            issuer,
        )

    candidates = tuple(
        sorted(
            {
                security.security_id
                for security in securities
                if security.cik == issuer.cik and security.security_type == "common_stock"
            }
        )
    )
    alias_backed = issuer_resolution_uses_cross_source_alias(issuer)
    if len(candidates) == 1:
        return (
            IdentityResolution(
                evidence_id=evidence.evidence_id,
                status="resolved",
                method="cik_exact",
                confidence=0.85 if alias_backed else 0.90,
                security_id=candidates[0],
                cik=issuer.cik,
                candidate_security_ids=candidates,
                reason=(
                    "CIK derived from exact cross-source issuer alias evidence; unique "
                    "common-stock security"
                    if alias_backed
                    else "CIK derived from exact SEC historical name; unique common-stock security"
                ),
            ),
            issuer,
        )
    if len(candidates) > 1:
        return (
            IdentityResolution(
                evidence_id=evidence.evidence_id,
                status="ambiguous",
                method="unresolved",
                confidence=0.0,
                candidate_security_ids=candidates,
                reason="SEC issuer resolved but multiple common-stock securities remain",
            ),
            issuer,
        )
    return (
        IdentityResolution(
            evidence_id=evidence.evidence_id,
            status="unresolved",
            method="unresolved",
            confidence=0.0,
            reason="SEC issuer resolved but no stable common-stock security exists in FDRE",
        ),
        issuer,
    )


def load_stable_securities(session: Session) -> tuple[StableSecurityRecord, ...]:
    """Load stable security-to-CIK associations without using current tickers as identity."""

    rows = session.execute(
        select(Security.id, Company.cik, Security.security_type, Security.share_class)
        .join(Company, Company.id == Security.company_id)
        .order_by(Company.cik, Security.id)
    ).all()
    return tuple(
        StableSecurityRecord(
            security_id=int(security_id),
            cik=normalize_cik(str(cik)),
            security_type=str(security_type),
            share_class=str(share_class) if share_class is not None else None,
        )
        for security_id, cik, security_type, share_class in rows
    )


def issuer_resolution_counts(
    resolutions: Sequence[IssuerNameResolution | None],
) -> Mapping[str, int]:
    counts = {"resolved": 0, "ambiguous": 0, "unresolved": 0, "not_attempted": 0}
    for resolution in resolutions:
        if resolution is None:
            counts["not_attempted"] += 1
        else:
            counts[resolution.status] = counts.get(resolution.status, 0) + 1
    return counts
