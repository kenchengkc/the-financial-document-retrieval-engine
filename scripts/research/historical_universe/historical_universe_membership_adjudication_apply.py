"""Apply one freshly replayed, frozen final HU-5 membership adjudication plan."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.research.historical_universe_membership_adjudication import (
    MembershipAdjudicationDecision,
    membership_adjudication_manifest_id,
    membership_adjudication_plan_id,
    plan_membership_adjudication,
)
from fdre.research.historical_universe_membership_adjudication_apply import (
    MEMBERSHIP_ADJUDICATION_APPLY_SCHEMA_VERSION,
    applied_membership_adjudication_source_hash,
    validate_membership_adjudication_projection,
)
from fdre.research.historical_universe_membership_adjudication_manifest import (
    HU5_MEMBERSHIP_ADJUDICATION_CASES,
)
from fdre.research.historical_universe_membership_continuity import normalize_cik
from scripts.research.historical_universe.historical_universe_membership_adjudication import (
    load_live_siblings,
)
from scripts.research.historical_universe.historical_universe_strict_coverage import (
    load_provisional_membership_blockers,
)

WINDOW_START = date(2010, 1, 1)
WINDOW_END = date(2026, 9, 1)
UNIVERSE_CODE = "sp500"


def _validate_request(*, apply: bool, expected_plan_id: str, allow_prod: bool) -> None:
    if not apply:
        raise RuntimeError("membership adjudication apply requires explicit --apply")
    if not allow_prod:
        raise RuntimeError("--apply requires FDRE_ALLOW_PROD=1")
    if len(expected_plan_id) != 64:
        raise RuntimeError("--expected-plan-id must be a SHA-256 plan id")


def _live_row(session: Session, decision: MembershipAdjudicationDecision) -> UniverseMembership:
    row = session.get(UniverseMembership, decision.membership_id)
    if row is None:
        raise RuntimeError(f"membership row {decision.membership_id} no longer exists")
    if row.security_id != decision.security_id:
        raise RuntimeError(f"membership row {decision.membership_id} security changed")
    if row.universe_code != UNIVERSE_CODE:
        raise RuntimeError(f"membership row {decision.membership_id} universe changed")
    if (
        row.effective_from != decision.prior_effective_from
        or row.effective_to != decision.prior_effective_to
    ):
        raise RuntimeError(f"membership row {decision.membership_id} interval changed")
    if row.source_hash != decision.prior_source_hash:
        raise RuntimeError(f"membership row {decision.membership_id} source hash changed")
    if row.verification_status != "provisional":
        raise RuntimeError(f"membership row {decision.membership_id} is no longer provisional")
    security = session.get(Security, row.security_id)
    if security is None:
        raise RuntimeError(f"security row {row.security_id} no longer exists")
    company = session.get(Company, security.company_id)
    if company is None or normalize_cik(str(company.cik)) != normalize_cik(decision.cik):
        raise RuntimeError(f"membership row {decision.membership_id} issuer CIK changed")
    return row


def _stage(
    session: Session,
    decisions: tuple[MembershipAdjudicationDecision, ...],
    *,
    plan_id: str,
    manifest_id: str,
) -> list[dict[str, object]]:
    rows = {item.membership_id: _live_row(session, item) for item in decisions}
    changes: list[dict[str, object]] = []
    for decision in decisions:
        row = rows[decision.membership_id]
        prior_source = str(row.source)
        if decision.action == "reject":
            row.verification_status = "rejected"
        else:
            row.effective_from = decision.target_effective_from
            row.effective_to = decision.target_effective_to
            row.verification_status = "verified"
        row.confidence = max(float(row.confidence), 0.99)
        row.source = f"{prior_source}|hu5-membership-adjudication"
        row.source_hash = applied_membership_adjudication_source_hash(
            decision,
            plan_id=plan_id,
            manifest_id=manifest_id,
        )
        changes.append(
            {
                "membership_id": row.id,
                "security_id": row.security_id,
                "action": decision.action,
                "prior_effective_from": decision.prior_effective_from.isoformat(),
                "prior_effective_to": (
                    decision.prior_effective_to.isoformat()
                    if decision.prior_effective_to
                    else None
                ),
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "prior_source": prior_source,
                "source": row.source,
                "prior_source_hash": decision.prior_source_hash,
                "source_hash": row.source_hash,
                "decision_hash": decision.decision_hash,
                "evidence_ids": list(decision.evidence_ids),
                "sibling_membership_ids": list(decision.sibling_membership_ids),
            }
        )
    session.flush()
    remaining = load_provisional_membership_blockers(
        session,
        universe_code=UNIVERSE_CODE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    if remaining:
        raise RuntimeError(
            "membership adjudication did not close the reviewed blocker inventory: "
            f"{len(remaining)} provisional memberships remain"
        )
    return changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the frozen final HU-5 membership adjudication plan."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--expected-plan-id", required=True)
    parser.add_argument("--expected-verify-count", type=int, required=True)
    parser.add_argument("--expected-correct-count", type=int, required=True)
    parser.add_argument("--expected-reject-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    _validate_request(
        apply=args.apply,
        expected_plan_id=args.expected_plan_id,
        allow_prod=os.environ.get("FDRE_ALLOW_PROD") == "1",
    )
    raw_payload: Any = json.loads(args.projection.read_text(encoding="utf-8"))
    decisions = validate_membership_adjudication_projection(
        raw_payload,
        expected_plan_id=args.expected_plan_id,
        cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
    )
    counts = Counter(item.action for item in decisions)
    expected_counts = {
        "verify": args.expected_verify_count,
        "correct_and_verify": args.expected_correct_count,
        "reject": args.expected_reject_count,
    }
    actual_counts = {action: counts[action] for action in expected_counts}
    if actual_counts != expected_counts:
        raise RuntimeError(
            f"membership adjudication action counts changed: {actual_counts}"
        )

    manifest_id = membership_adjudication_manifest_id(HU5_MEMBERSHIP_ADJUDICATION_CASES)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            blockers = load_provisional_membership_blockers(
                session,
                universe_code=UNIVERSE_CODE,
                window_start=WINDOW_START,
                window_end=WINDOW_END,
            )
            siblings = load_live_siblings(session)
            fresh = plan_membership_adjudication(
                blockers,
                cases=HU5_MEMBERSHIP_ADJUDICATION_CASES,
                live_siblings=siblings,
            )
            fresh_plan_id = membership_adjudication_plan_id(
                fresh,
                manifest_id=manifest_id,
            )
            if fresh != decisions or fresh_plan_id != args.expected_plan_id:
                raise RuntimeError("live membership adjudication replay differs from frozen plan")
            changes = _stage(
                session,
                fresh,
                plan_id=args.expected_plan_id,
                manifest_id=manifest_id,
            )
            session.commit()
    finally:
        engine.dispose()

    result = {
        "schema_version": MEMBERSHIP_ADJUDICATION_APPLY_SCHEMA_VERSION,
        "mode": "apply",
        "manifest_id": manifest_id,
        "plan_id": args.expected_plan_id,
        "applied_membership_updates": len(changes),
        "action_counts": actual_counts,
        "remaining_provisional_memberships": 0,
        "changes": changes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest_id": manifest_id,
                "plan_id": args.expected_plan_id,
                "applied_membership_updates": len(changes),
                "action_counts": actual_counts,
                "remaining_provisional_memberships": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
