"""Project conservative HU-5 membership continuity decisions against production state."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.research.historical_universe_membership_continuity import (
    MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
    CurrentConstituentAnchorAdapter,
    VerifiedSiblingMembership,
    membership_continuity_plan_id,
    normalize_cik,
    plan_membership_continuity,
)
from scripts.research.historical_universe.historical_universe_strict_coverage import (
    load_provisional_membership_blockers,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _verified_siblings(
    session: Session,
    *,
    blocker_ciks: set[str],
    universe_code: str,
) -> tuple[VerifiedSiblingMembership, ...]:
    if not blocker_ciks:
        return ()
    normalized = universe_code.strip().lower()
    rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.security_id,
            Company.cik,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.source_hash,
        )
        .join(Security, Security.id == UniverseMembership.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            UniverseMembership.universe_code == normalized,
            UniverseMembership.verification_status == "verified",
            Company.cik.in_(sorted(blocker_ciks)),
        )
        .order_by(UniverseMembership.id)
    ).all()
    return tuple(
        VerifiedSiblingMembership(
            membership_id=int(sibling_row.id),
            security_id=int(sibling_row.security_id),
            cik=normalize_cik(str(sibling_row.cik)),
            effective_from=sibling_row.effective_from,
            effective_to=sibling_row.effective_to,
            source_hash=str(sibling_row.source_hash),
        )
        for sibling_row in rows
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project HU-5 membership continuity decisions.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--current-constituents", type=Path, required=True)
    parser.add_argument("--current-constituents-ref", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    anchors = CurrentConstituentAnchorAdapter(
        source_ref=args.current_constituents_ref
    ).load(args.current_constituents)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            blockers = load_provisional_membership_blockers(
                session,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            blocker_ciks = {normalize_cik(item.cik) for item in blockers}
            siblings = _verified_siblings(
                session,
                blocker_ciks=blocker_ciks,
                universe_code=args.universe_code,
            )
            decisions = plan_membership_continuity(
                blockers,
                current_anchors=anchors,
                verified_siblings=siblings,
            )
            session.rollback()
    finally:
        engine.dispose()

    plan_id = membership_continuity_plan_id(
        decisions,
        current_source_ref=args.current_constituents_ref,
    )
    counts = {
        action: sum(item.action == action for item in decisions)
        for action in ("verify", "reject", "unresolved")
    }
    used_evidence_ids = {
        evidence_id
        for decision in decisions
        for evidence_id in decision.evidence_ids
    }
    anchor_evidence = [
        {
            "evidence_id": anchor.evidence_id,
            "symbol": anchor.symbol,
            "cik": anchor.cik,
            "date_added": anchor.date_added.isoformat(),
            "source_ref": anchor.source_ref,
            "source_hash": anchor.source_hash,
            "row_hash": anchor.row_hash,
        }
        for anchor in anchors
        if anchor.evidence_id in used_evidence_ids
    ]
    sibling_evidence = [
        {
            "evidence_id": sibling.evidence_id,
            "membership_id": sibling.membership_id,
            "security_id": sibling.security_id,
            "cik": sibling.cik,
            "effective_from": sibling.effective_from.isoformat(),
            "effective_to": sibling.effective_to.isoformat() if sibling.effective_to else None,
            "source_hash": sibling.source_hash,
        }
        for sibling in siblings
        if sibling.evidence_id in used_evidence_ids
    ]
    payload = {
        "schema_version": MEMBERSHIP_CONTINUITY_SCHEMA_VERSION,
        "mode": "projection",
        "plan_id": plan_id,
        "universe_code": args.universe_code.strip().lower(),
        "window_start": args.window_start.isoformat(),
        "window_end": args.window_end.isoformat(),
        "current_constituents_ref": args.current_constituents_ref,
        "blocker_count": len(blockers),
        "decision_counts": counts,
        "decisions": [item.as_dict() for item in decisions],
        "evidence": {
            "current_constituent_anchors": anchor_evidence,
            "verified_sibling_memberships": sibling_evidence,
        },
        "interpretation": (
            "Read-only fail-closed projection. Verify decisions require an exact pinned current "
            "CIK+active-symbol anchor covering the open membership start. Reject decisions require "
            "exactly one already-verified sibling membership for the same issuer to cover the "
            "entire provisional interval. Multi-class ambiguity and all other shapes remain "
            "unresolved."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": plan_id,
                "blocker_count": len(blockers),
                "decision_counts": counts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
