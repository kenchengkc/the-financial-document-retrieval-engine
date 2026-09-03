"""Project exact SEC-backed rejection of non-common Historical Universe contamination.

The command is deliberately read-only. It requires one unambiguous provisional SGPPRB identity
and one overlapping provisional S&P 500 membership for the same security, independently fetches
immutable SEC evidence that the listed security was preferred stock rather than common stock,
stages both rejections only long enough to measure HU-5 strict-coverage impact, and rolls back.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_security_type import (
    SecurityTypeAdjudicationTarget,
    extract_schering_plough_preferred_evidence,
    plan_security_type_adjudication,
    security_symbol_key,
    security_type_plan_id,
)
from fdre.research.hu5_universe import build_hu5_universe_gate, load_hu5_universe_records

PROJECTION_SCHEMA_VERSION = "fdre-hu-security-type-adjudication-projection-v1"
TARGET_CIK = "0000310158"
TARGET_SYMBOL = "SGPPRB"
SEC_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/310158/000095012307011295/y37189bte424b2.htm"
)
DEFAULT_SEC_USER_AGENT = (
    "FDRE historical-universe research "
    "https://github.com/kenchengkc/the-financial-document-retrieval-engine"
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


def _target_from_identity(
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


def _target_from_membership(
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


def load_exact_sgpprb_targets(
    session: Session,
) -> tuple[
    tuple[SecurityTypeAdjudicationTarget, ...],
    SecurityIdentityPeriod,
    UniverseMembership,
]:
    """Load the one exact provisional SGPPRB identity and overlapping S&P membership."""

    identity_rows = session.execute(
        select(SecurityIdentityPeriod, Company.cik)
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            SecurityIdentityPeriod.verification_status == "provisional",
            Company.cik == TARGET_CIK,
        )
        .order_by(SecurityIdentityPeriod.id)
    ).all()
    exact_identities = [
        (row, normalize_cik(str(cik)))
        for row, cik in identity_rows
        if security_symbol_key(row.symbol) == TARGET_SYMBOL
    ]
    if len(exact_identities) != 1:
        raise RuntimeError(
            "SGPPRB adjudication requires exactly one provisional identity; "
            f"found {len(exact_identities)}"
        )
    identity, cik = exact_identities[0]
    if cik != TARGET_CIK:
        raise RuntimeError(f"SGPPRB identity issuer CIK changed: {cik}")

    membership_rows = tuple(
        session.scalars(
            select(UniverseMembership)
            .where(
                UniverseMembership.universe_code == "sp500",
                UniverseMembership.security_id == identity.security_id,
                UniverseMembership.verification_status == "provisional",
            )
            .order_by(UniverseMembership.id)
        )
    )
    exact_memberships = [
        row
        for row in membership_rows
        if _overlaps(
            row.effective_from,
            row.effective_to,
            identity.effective_from,
            identity.effective_to,
        )
    ]
    if len(exact_memberships) != 1:
        raise RuntimeError(
            "SGPPRB adjudication requires exactly one overlapping provisional S&P 500 membership; "
            f"found {len(exact_memberships)}"
        )
    membership = exact_memberships[0]
    targets = (
        _target_from_identity(identity, cik=cik),
        _target_from_membership(membership, cik=cik, symbol=identity.symbol),
    )
    return targets, identity, membership


def fetch_sec_security_type_evidence(
    *,
    source_url: str,
    user_agent: str,
) -> object:
    with httpx.Client(
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        response = client.get(source_url)
        response.raise_for_status()
        return extract_schering_plough_preferred_evidence(
            response.content,
            source_url=str(response.url),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only projection of SEC-backed SGPPRB security-type adjudication."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--sec-source-url", default=SEC_SOURCE_URL)
    parser.add_argument(
        "--sec-user-agent",
        default=os.environ.get("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT),
    )
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.window_end < args.window_start:
        raise RuntimeError("window end must not precede window start")

    evidence = fetch_sec_security_type_evidence(
        source_url=args.sec_source_url,
        user_agent=args.sec_user_agent,
    )
    if not hasattr(evidence, "evidence_id"):
        raise RuntimeError("invalid SEC security-type evidence result")

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            targets, identity, membership = load_exact_sgpprb_targets(session)
            decisions = plan_security_type_adjudication(targets, evidence)  # type: ignore[arg-type]
            rejection_count = sum(item.rejection_candidate for item in decisions)
            if rejection_count != 2:
                raise RuntimeError(
                    "SGPPRB projection must reject exactly one identity and one membership; "
                    f"projected {rejection_count}"
                )
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

            identity.verification_status = "rejected"
            membership.verification_status = "rejected"
            session.flush()

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
            session.rollback()
    finally:
        engine.dispose()

    payload = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "mode": "projection",
        "applied": False,
        "plan_id": plan_id,
        "target_cik": TARGET_CIK,
        "target_symbol": TARGET_SYMBOL,
        "sec_evidence": evidence.as_dict(),  # type: ignore[union-attr]
        "target_count": len(targets),
        "rejection_candidate_count": rejection_count,
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
            "Read-only projection. Exact live SGPPRB identity and membership rows were matched to "
            "immutable SEC evidence that SGP PrB was preferred stock while SGP was the issuer's "
            "common-share symbol. Both rows were staged as rejected only to measure HU-5 impact "
            "and the transaction was rolled back."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": plan_id,
                "rejection_candidate_count": rejection_count,
                "strict_eligible_days_before": before_gate.strict_eligible_day_count,
                "strict_eligible_days_projected": after_gate.strict_eligible_day_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
