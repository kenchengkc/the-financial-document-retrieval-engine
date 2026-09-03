"""SEC security-type evidence for rejecting non-common HU ticker contamination.

This layer is intentionally narrower than issuer/ticker identity matching. It does not infer a
security type from ticker spelling. A rejection candidate requires an immutable SEC payload that
explicitly describes the target listed symbol as a non-common security and separately identifies
the issuer's common-share symbol.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

from bs4 import BeautifulSoup

SecurityType = Literal["common_stock", "preferred_stock"]
AdjudicationRowKind = Literal["membership", "identity"]
AdjudicationStatus = Literal["reject_non_common_security", "unresolved"]

SEC_SECURITY_TYPE_EVIDENCE_SCHEMA_VERSION = "fdre-hu-sec-security-type-evidence-v1"
SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION = "fdre-hu-security-type-adjudication-v1"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def security_symbol_key(value: str) -> str:
    """Normalize presentation separators only for exact listed-symbol comparison."""

    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _document_text(content: str | bytes) -> str:
    soup = BeautifulSoup(content, "lxml")
    return " ".join(soup.get_text(" ", strip=True).split())


@dataclass(frozen=True, slots=True)
class SecSecurityTypeEvidence:
    cik: str
    listed_symbol: str
    security_type: SecurityType
    common_symbol: str
    source_url: str
    payload_sha256: str
    assertion: str

    def __post_init__(self) -> None:
        if not self.cik.isdigit() or len(self.cik) != 10:
            raise ValueError("cik must be a zero-padded 10-digit string")
        if not security_symbol_key(self.listed_symbol):
            raise ValueError("listed_symbol is required")
        if not security_symbol_key(self.common_symbol):
            raise ValueError("common_symbol is required")
        if security_symbol_key(self.listed_symbol) == security_symbol_key(self.common_symbol):
            raise ValueError("non-common evidence must identify a distinct common-share symbol")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be SHA-256")
        if not self.source_url.startswith("https://www.sec.gov/Archives/edgar/data/"):
            raise ValueError("security-type evidence must come from immutable SEC EDGAR archives")

    @property
    def evidence_id(self) -> str:
        return _digest(
            {
                "schema_version": SEC_SECURITY_TYPE_EVIDENCE_SCHEMA_VERSION,
                "cik": self.cik,
                "listed_symbol": self.listed_symbol,
                "security_type": self.security_type,
                "common_symbol": self.common_symbol,
                "source_url": self.source_url,
                "payload_sha256": self.payload_sha256,
                "assertion": self.assertion,
            }
        )

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_id"] = self.evidence_id
        return payload


def extract_schering_plough_preferred_evidence(
    content: str | bytes,
    *,
    source_url: str,
) -> SecSecurityTypeEvidence:
    """Extract the exact SGP PrB/common-SGP distinction from the 2007 SEC prospectus.

    This is deliberately evidence-scoped rather than a general preferred-ticker classifier. The
    payload must explicitly call the instrument mandatory convertible preferred stock, bind it to
    ``SGP PrB``, and separately bind the issuer's common shares to ``SGP``.
    """

    payload = content.encode("utf-8") if isinstance(content, str) else content
    text = _document_text(payload)
    preferred = re.search(
        r"6\.00%\s+mandatory\s+convertible\s+preferred\s+stock.{0,1800}?"
        r"approved\s+for\s+listing\s+on\s+the\s+new\s+york\s+stock\s+exchange.{0,300}?"
        r"under\s+the\s+symbol\s+[\"'“”]?SGP\s*PrB",
        text,
        flags=re.IGNORECASE,
    )
    common = re.search(
        r"common\s+shares\s+are\s+listed\s+on\s+the\s+new\s+york\s+stock\s+exchange.{0,160}?"
        r"under\s+the\s+symbol\s+[\"'“”]?SGP",
        text,
        flags=re.IGNORECASE,
    )
    if preferred is None or common is None:
        raise ValueError(
            "SEC payload does not explicitly bind SGP PrB to preferred stock and SGP to common shares"
        )
    return SecSecurityTypeEvidence(
        cik="0000310158",
        listed_symbol="SGPPRB",
        security_type="preferred_stock",
        common_symbol="SGP",
        source_url=source_url,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        assertion=(
            "SEC prospectus explicitly identifies SGP PrB as 6.00% mandatory convertible "
            "preferred stock and separately identifies SGP as Schering-Plough common shares"
        ),
    )


@dataclass(frozen=True, slots=True)
class SecurityTypeAdjudicationTarget:
    row_kind: AdjudicationRowKind
    row_id: int
    security_id: int
    cik: str
    symbol: str
    prior_source_hash: str
    verification_status: str

    def __post_init__(self) -> None:
        if self.row_id <= 0 or self.security_id <= 0:
            raise ValueError("row_id and security_id must be positive")
        if not self.cik.isdigit() or len(self.cik) != 10:
            raise ValueError("cik must be a zero-padded 10-digit string")
        if len(self.prior_source_hash) != 64:
            raise ValueError("prior_source_hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class SecurityTypeAdjudicationDecision:
    row_kind: AdjudicationRowKind
    row_id: int
    security_id: int
    cik: str
    symbol: str
    prior_source_hash: str
    status: AdjudicationStatus
    evidence_id: str | None
    reason: str
    decision_hash: str

    @property
    def rejection_candidate(self) -> bool:
        return self.status == "reject_non_common_security"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["rejection_candidate"] = self.rejection_candidate
        return payload


def plan_security_type_adjudication(
    targets: tuple[SecurityTypeAdjudicationTarget, ...],
    evidence: SecSecurityTypeEvidence,
) -> tuple[SecurityTypeAdjudicationDecision, ...]:
    """Reject only exact provisional rows bound to the SEC-proven non-common listed symbol."""

    decisions: list[SecurityTypeAdjudicationDecision] = []
    seen: set[tuple[str, int]] = set()
    evidence_symbol = security_symbol_key(evidence.listed_symbol)
    common_symbol = security_symbol_key(evidence.common_symbol)
    for target in sorted(targets, key=lambda item: (item.row_kind, item.row_id)):
        key = (target.row_kind, target.row_id)
        if key in seen:
            raise ValueError(f"duplicate adjudication target {target.row_kind}:{target.row_id}")
        seen.add(key)
        exact_match = (
            target.verification_status == "provisional"
            and target.cik == evidence.cik
            and security_symbol_key(target.symbol) == evidence_symbol
            and evidence.security_type != "common_stock"
            and evidence_symbol != common_symbol
        )
        if exact_match:
            status: AdjudicationStatus = "reject_non_common_security"
            evidence_id: str | None = evidence.evidence_id
            reason = (
                "immutable SEC offering evidence identifies this exact listed symbol as preferred "
                "stock while separately identifying a different symbol for the issuer's common "
                "shares; it cannot represent common-stock S&P 500 membership/identity"
            )
        else:
            status = "unresolved"
            evidence_id = None
            reason = (
                "target is not an exact provisional CIK/symbol match for the SEC-proven non-common "
                "security; no rejection is permitted"
            )
        decision_payload = {
            "schema_version": SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION,
            "row_kind": target.row_kind,
            "row_id": target.row_id,
            "security_id": target.security_id,
            "cik": target.cik,
            "symbol": target.symbol,
            "prior_source_hash": target.prior_source_hash,
            "status": status,
            "evidence_id": evidence_id,
        }
        decisions.append(
            SecurityTypeAdjudicationDecision(
                row_kind=target.row_kind,
                row_id=target.row_id,
                security_id=target.security_id,
                cik=target.cik,
                symbol=target.symbol,
                prior_source_hash=target.prior_source_hash,
                status=status,
                evidence_id=evidence_id,
                reason=reason,
                decision_hash=_digest(decision_payload),
            )
        )
    return tuple(decisions)


def security_type_plan_id(decisions: tuple[SecurityTypeAdjudicationDecision, ...]) -> str:
    return _digest(
        {
            "schema_version": SEC_SECURITY_TYPE_DECISION_SCHEMA_VERSION,
            "decision_hashes": [item.decision_hash for item in decisions],
        }
    )
