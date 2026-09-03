"""Read-only SEC-backed projection for the known SGPPRB Historical Universe blocker.

This command anchors discovery on membership row 580, snapshots its live issuer/security/identity
shape, verifies immutable SEC evidence that SGP PrB was preferred stock while SGP was the issuer's
common-share symbol, and projects only evidence-supported rejection candidates. Any candidate
rejections are staged solely to measure HU-5 strict-coverage impact and are always rolled back.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.ingestion.sec_client import SECClient
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_security_type import (
    SecSecurityTypeEvidence,
    SecurityTypeAdjudicationDecision,
    SecurityTypeAdjudicationTarget,
    extract_schering_plough_preferred_evidence,
    plan_security_type_adjudication,
    security_symbol_key,
    security_type_plan_id,
)
from fdre.research.hu5_universe import build_hu5_universe_gate, load_hu5_universe_records

PROJECTION_SCHEMA_VERSION = "fdre-hu-security-type-adjudication-projection-v2"
BLOCKER_MEMBERSHIP_ID = 580
TARGET_CIK = "0000310158"
TARGET_SYMBOL = "SGPPRB"
SEC_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/310158/000095012307011295/y37189bte424b2.htm"
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _overlaps(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (right_end is None or left_start < right_end) and (
        left_end is None or right_start < left_end
    )


def _identity_snapshot(row: SecurityIdentityPeriod) -> dict[str, object]:
    return {
        "row_id": row.id,
        "security_id": row.security_id,
        "symbol": row.symbol,
        "symbol_key": security_symbol_key(row.symbol),
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": row.source,
        "source_url": row.source_url,
        "source_hash": row.source_hash,
        "verification_status": row.verification_status,
        "confidence": float(row.confidence),
    }


def _membership_snapshot(row: UniverseMembership) -> dict[str, object]:
    return {
        "row_id": row.id,
        "universe_code": row.universe_code,
        "security_id": row.security_id,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "source": row.source,
        "source_url": row.source_url,
        "source_hash": row.source_hash,
        "verification_status": row.verification_status,
        "confidence": float(row.confidence),
    }


def _identity_target(
    row: SecurityIdentityPeriod,
    *,
    cik: str,
) -> SecurityTypeAdjudicationTarget:
    return SecurityTypeAdjudicationTarget(
        row_kind="identity",
        row_id=row.id,
        security_id=row.security_id,
        cik=cik,
        symbol=row.symbol,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        prior_source_hash=row.source_hash,
        verification_status=row.verification_status,
    )


def _membership_target(
    row: UniverseMembership,
    *,
    cik: str,
    symbol: str,
) -> SecurityTypeAdjudicationTarget:
    return SecurityTypeAdjudicationTarget(
        row_kind="membership",
        row_id=row.id,
        security_id=row.security_id,
        cik=cik,
        symbol=symbol,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        prior_source_hash=row.source_hash,
        verification_status=row.verification_status,
    )


def discover_sgpprb_blocker(
    session: Session,
) -> tuple[
    UniverseMembership,
    Security,
    Company,
    tuple[SecurityIdentityPeriod, ...],
    tuple[SecurityIdentityPeriod, ...],
]:
    """Load blocker row 580 and expose its live issuer/identity shape without inference."""

    membership = session.get(UniverseMembership, BLOCKER_MEMBERSHIP_ID)
    if membership is None:
        raise RuntimeError(f"known HU blocker membership {BLOCKER_MEMBERSHIP_ID} no longer exists")
    if membership.universe_code != "sp500":
        raise RuntimeError(
            f"membership {BLOCKER_MEMBERSHIP_ID} universe changed to {membership.universe_code!r}"
        )

    security = session.get(Security, membership.security_id)
    if security is None:
        raise RuntimeError(f"security {membership.security_id} no longer exists")
    company = session.get(Company, security.company_id)
    if company is None:
        raise RuntimeError(f"company {security.company_id} no longer exists")

    identities = tuple(
        session.scalars(
            select(SecurityIdentityPeriod)
            .where(SecurityIdentityPeriod.security_id == security.id)
            .order_by(SecurityIdentityPeriod.effective_from, SecurityIdentityPeriod.id)
        )
    )
    overlapping_sgpprb = tuple(
        row
        for row in identities
        if security_symbol_key(row.symbol) == TARGET_SYMBOL
        and _overlaps(
            row.effective_from,
            row.effective_to,
            membership.effective_from,
            membership.effective_to,
        )
    )
    return membership, security, company, identities, overlapping_sgpprb


def _adjudication_targets(
    membership: UniverseMembership,
    overlapping_sgpprb: tuple[SecurityIdentityPeriod, ...],
    *,
    issuer_cik: str,
) -> tuple[SecurityTypeAdjudicationTarget, ...]:
    """Build targets only when one identity unambiguously binds row 580 to SGPPRB."""

    if len(overlapping_sgpprb) != 1:
        return ()
    identity = overlapping_sgpprb[0]
    return (
        _identity_target(identity, cik=issuer_cik),
        _membership_target(membership, cik=issuer_cik, symbol=identity.symbol),
    )


def _stage_rejections(
    session: Session,
    decisions: tuple[SecurityTypeAdjudicationDecision, ...],
) -> int:
    """Stage exact candidate rejections after rechecking live status and source hashes."""

    staged = 0
    for decision in decisions:
        if not decision.rejection_candidate:
            continue
        row: UniverseMembership | SecurityIdentityPeriod | None
        if decision.row_kind == "membership":
            row = session.get(UniverseMembership, decision.row_id)
        else:
            row = session.get(SecurityIdentityPeriod, decision.row_id)
        if row is None:
            raise RuntimeError(f"adjudication row disappeared: {decision.row_kind}:{decision.row_id}")
        if row.verification_status != "provisional":
            raise RuntimeError(
                f"adjudication row is no longer provisional: {decision.row_kind}:{decision.row_id}"
            )
        if row.source_hash != decision.prior_source_hash:
            raise RuntimeError(
                f"adjudication row source changed: {decision.row_kind}:{decision.row_id}"
            )
        row.verification_status = "rejected"
        staged += 1
    session.flush()
    return staged


def fetch_sec_security_type_evidence(
    *,
    source_url: str = SEC_SOURCE_URL,
) -> SecSecurityTypeEvidence:
    """Fetch the immutable SEC prospectus using the repository's compliant SEC client."""

    with SECClient.from_settings() as client:
        payload = client.get_bytes(source_url)
    return extract_schering_plough_preferred_evidence(payload, source_url=source_url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only live projection for SEC-backed SGPPRB adjudication."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--sec-source-url", default=SEC_SOURCE_URL)
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.window_end < args.window_start:
        raise RuntimeError("window end must not precede window start")

    evidence = fetch_sec_security_type_evidence(source_url=args.sec_source_url)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            membership, security, company, identities, overlapping = discover_sgpprb_blocker(
                session
            )
            issuer_cik = normalize_cik(company.cik)

            # Snapshot ORM-backed values before rollback so the audit artifact remains serializable.
            membership_snapshot = _membership_snapshot(membership)
            security_snapshot: dict[str, object] = {
                "security_id": security.id,
                "company_id": security.company_id,
                "security_type": security.security_type,
                "share_class": security.share_class,
            }
            company_snapshot: dict[str, object] = {
                "company_id": company.id,
                "cik": issuer_cik,
                "ticker": company.ticker,
                "name": company.name,
            }
            identity_snapshots = [_identity_snapshot(row) for row in identities]
            overlapping_snapshots = [_identity_snapshot(row) for row in overlapping]

            if len(overlapping) == 1:
                bridge_status = "unique_sgpprb_identity"
            elif not overlapping:
                bridge_status = "no_overlapping_sgpprb_identity"
            else:
                bridge_status = "ambiguous_overlapping_sgpprb_identities"

            targets = _adjudication_targets(
                membership,
                overlapping,
                issuer_cik=issuer_cik,
            )
            decisions = plan_security_type_adjudication(targets, evidence)
            rejection_count = sum(item.rejection_candidate for item in decisions)
            status_counts = Counter(item.status for item in decisions)
            plan_id = security_type_plan_id(decisions)

            before_records = load_hu5_universe_records(
                session,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )
            before_gate = build_hu5_universe_gate(
                before_records,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )

            staged_count = _stage_rejections(session, decisions)
            after_records = load_hu5_universe_records(
                session,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )
            after_gate = build_hu5_universe_gate(
                after_records,
                universe_code="sp500",
                window_start=args.window_start,
                window_end=args.window_end,
            )

            payload: dict[str, object] = {
                "schema_version": PROJECTION_SCHEMA_VERSION,
                "mode": "projection",
                "applied": False,
                "plan_id": plan_id,
                "known_blocker_membership_id": BLOCKER_MEMBERSHIP_ID,
                "target_sec_cik": TARGET_CIK,
                "target_symbol": TARGET_SYMBOL,
                "sec_evidence": evidence.as_dict(),
                "discovery": {
                    "membership": membership_snapshot,
                    "security": security_snapshot,
                    "company": company_snapshot,
                    "identity_periods": identity_snapshots,
                    "overlapping_sgpprb_identity_count": len(overlapping_snapshots),
                    "overlapping_sgpprb_identities": overlapping_snapshots,
                    "bridge_status": bridge_status,
                    "issuer_matches_sec_evidence": issuer_cik == evidence.cik,
                },
                "target_count": len(targets),
                "rejection_candidate_count": rejection_count,
                "staged_rejection_count": staged_count,
                "status_counts": dict(sorted(status_counts.items())),
                "decisions": [item.as_dict() for item in decisions],
                "strict_coverage_before": {
                    "gate_manifest_id": before_gate.gate_manifest_id,
                    "input_provenance_id": before_gate.input_provenance_id,
                    "strict_eligible_day_count": before_gate.strict_eligible_day_count,
                    "invalid_day_count": before_gate.invalid_day_count,
                    "day_count": before_gate.day_count,
                },
                "strict_coverage_projected": {
                    "gate_manifest_id": after_gate.gate_manifest_id,
                    "input_provenance_id": after_gate.input_provenance_id,
                    "strict_eligible_day_count": after_gate.strict_eligible_day_count,
                    "invalid_day_count": after_gate.invalid_day_count,
                    "day_count": after_gate.day_count,
                },
                "interpretation": (
                    "Read-only production projection anchored on blocker membership 580. Exact "
                    "issuer/security/identity state is snapshotted before rollback. Rejection is "
                    "permitted only through one unambiguous overlapping SGPPRB identity and exact "
                    "SEC-backed CIK/symbol/status matching; verified identities are never "
                    "overridden by this planner."
                ),
            }
            summary: dict[str, object] = {
                "plan_id": plan_id,
                "membership": membership_snapshot,
                "security": security_snapshot,
                "company": company_snapshot,
                "bridge_status": bridge_status,
                "overlapping_sgpprb_identities": overlapping_snapshots,
                "rejection_candidate_count": rejection_count,
                "strict_eligible_days_before": before_gate.strict_eligible_day_count,
                "strict_eligible_days_projected": after_gate.strict_eligible_day_count,
            }
            session.rollback()
    finally:
        engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
