"""Project the reviewed final HU-5 membership adjudications against live database state."""

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
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.research.historical_universe_membership_adjudication import (
    MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
    LiveSiblingMembership,
    membership_adjudication_manifest_id,
    membership_adjudication_plan_id,
    plan_membership_adjudication,
)
from fdre.research.historical_universe_membership_adjudication_manifest import (
    HU5_MEMBERSHIP_ADJUDICATION_CASES,
)
from scripts.research.historical_universe.historical_universe_strict_coverage import (
    load_provisional_membership_blockers,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _required_sibling_ids() -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                sibling.membership_id
                for case in HU5_MEMBERSHIP_ADJUDICATION_CASES
                for sibling in case.siblings
            }
        )
    )


def load_live_siblings(session: Session) -> tuple[LiveSiblingMembership, ...]:
    sibling_ids = _required_sibling_ids()
    if not sibling_ids:
        return ()
    rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.security_id,
            Company.cik,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.source_hash,
            UniverseMembership.verification_status,
        )
        .join(Security, Security.id == UniverseMembership.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(UniverseMembership.id.in_(sibling_ids))
        .order_by(UniverseMembership.id)
    ).all()
    return tuple(
        LiveSiblingMembership(
            membership_id=int(row.id),
            security_id=int(row.security_id),
            cik=str(row.cik),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=str(row.verification_status),
        )
        for row in rows
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project the reviewed final HU-5 membership adjudication manifest."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            blockers = load_provisional_membership_blockers(
                session,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            siblings = load_live_siblings(session)
            decisions = plan_membership_adjudication(
                blockers,
                cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
                live_siblings=siblings,
            )
            session.rollback()
    finally:
        engine.dispose()

    manifest_id = membership_adjudication_manifest_id(HU5_MEMBERSHIP_ADJUDICATION_CASES)
    plan_id = membership_adjudication_plan_id(decisions, manifest_id=manifest_id)
    counts = Counter(item.action for item in decisions)
    evidence_by_id = {
        evidence.evidence_id: evidence
        for case in HU5_MEMBERSHIP_ADJUDICATION_CASES
        for evidence in case.evidence
    }
    payload = {
        "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
        "mode": "projection",
        "manifest_id": manifest_id,
        "plan_id": plan_id,
        "universe_code": args.universe_code.strip().lower(),
        "window_start": args.window_start.isoformat(),
        "window_end": args.window_end.isoformat(),
        "blocker_count": len(blockers),
        "decision_counts": {
            action: counts[action]
            for action in ("verify", "correct_and_verify", "reject")
        },
        "decisions": [item.as_dict() for item in decisions],
        "manifest_cases": [
            {
                **case.canonical_dict(),
                "decision_hash": case.decision_hash,
            }
            for case in sorted(
                HU5_MEMBERSHIP_ADJUDICATION_CASES,
                key=lambda item: item.membership_id,
            )
        ],
        "evidence": [
            evidence_by_id[evidence_id].as_dict()
            for evidence_id in sorted(evidence_by_id)
        ],
        "live_siblings": [
            {
                "membership_id": item.membership_id,
                "security_id": item.security_id,
                "cik": item.cik,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "source_hash": item.source_hash,
                "verification_status": item.verification_status,
            }
            for item in siblings
        ],
        "interpretation": (
            "Read-only fail-closed HU-5 membership projection. Every live provisional membership "
            "must exactly match the checked-in reviewed manifest, its identity anchor, and any "
            "required verified sibling membership before a decision is emitted. Membership "
            "verification here does not repair provisional ticker identity periods and does not "
            "constitute final HU-5 completion."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest_id": manifest_id,
                "plan_id": plan_id,
                "blocker_count": len(blockers),
                "decision_counts": payload["decision_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
