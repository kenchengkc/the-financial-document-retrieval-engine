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
from datetime import datetime
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
_ISSUER_EVIDENCE_SCHEMA_VERSION = "fdre-hu-issuer-name-evidence-v1"
_ISSUER_RESOLUTION_SCHEMA_VERSION = "fdre-hu-issuer-name-resolution-v1"


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


@dataclass(frozen=True, slots=True)
class IssuerNameEvidence:
    """One exact name-to-CIK association observed in the SEC cumulative lookup."""

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
class IssuerNameResolution:
    """Exact historical issuer-name resolution result."""

    raw_name: str | None
    normalized_name: str | None
    status: IssuerResolutionStatus
    cik: str | None
    candidate_ciks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
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
    """Compact exact-name index over the SEC cumulative CIK lookup."""

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
            raise ValueError("SEC CIK lookup name cannot normalize to empty")
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
        }
    )
    return IssuerNameResolution(
        raw_name=raw_name,
        normalized_name=normalized,
        status=status,
        cik=cik,
        candidate_ciks=ciks,
        evidence_ids=evidence_ids,
        resolution_hash=resolution_hash,
        reason=reason,
    )


def resolve_membership_with_sec_issuer_fallback(
    evidence: MembershipEvidence,
    *,
    identities: Sequence[SecurityIdentityRecord],
    issuer_index: SecCikNameIndex,
    securities: Sequence[StableSecurityRecord],
) -> tuple[IdentityResolution, IssuerNameResolution | None]:
    """Resolve membership evidence without inventing historical ticker periods.

    Existing HU-1 date-aware ticker/CIK identity periods always get first priority. Only when
    they return ``unresolved`` do we attempt exact SEC historical-name resolution. A unique CIK
    can resolve to a stable security only when exactly one listed security exists for that CIK;
    multiple share classes fail closed as ambiguous.
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
    if len(candidates) == 1:
        return (
            IdentityResolution(
                evidence_id=evidence.evidence_id,
                status="resolved",
                method="cik_exact",
                confidence=0.90,
                security_id=candidates[0],
                cik=issuer.cik,
                candidate_security_ids=candidates,
                reason="CIK derived from exact SEC historical name; unique common-stock security",
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
