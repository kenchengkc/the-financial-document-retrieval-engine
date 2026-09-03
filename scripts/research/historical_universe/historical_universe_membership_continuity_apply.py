"""Apply a freshly replayed, frozen HU-5 membership continuity plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.research.historical_universe_membership_continuity import (
    MembershipContinuityDecision,
    normalize_cik,
)
from fdre.research.historical_universe_membership_continuity_apply import (
    MEMBERSHIP_CONTINUITY_APPLY_SCHEMA_VERSION,
    applied_membership_source_hash,
    validate_membership_continuity_projection,
)


def _validate_request(*, apply: bool, expected_plan_id: str, allow_prod: bool) -> None:
    if not apply:
        raise RuntimeError("membership continuity apply requires explicit --apply")
    if not allow_prod:
        raise RuntimeError("--apply requires FDRE_ALLOW_PROD=1")
    if len(expected_plan_id) != 64:
        raise RuntimeError("--expected-plan-id must be a SHA-256 plan id")


def _live_row(session: Session, decision: MembershipContinuityDecision) -> UniverseMembership:
    row = session.get(UniverseMembership, decision.membership_id)
    if row is None:
        raise RuntimeError(f"membership row {decision.membership_id} no longer exists")
    if row.security_id != decision.security_id:
        raise RuntimeError(f"membership row {decision.membership_id} security changed")
    if row.universe_code != "sp500":
        raise RuntimeError(f"membership row {decision.membership_id} universe changed")
    if row.effective_from != decision.effective_from or row.effective_to != decision.effective_to:
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
    decisions: tuple[MembershipContinuityDecision, ...],
    *,
    plan_id: str,
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    actionable = [item for item in decisions if item.action != "unresolved"]
    # Revalidate every target before the first write so a drifted plan is all-or-nothing.
    rows = {item.membership_id: _live_row(session, item) for item in actionable}
    for decision in actionable:
        row = rows[decision.membership_id]
        prior_source = str(row.source)
        row.verification_status = "verified" if decision.action == "verify" else "rejected"
        row.confidence = max(float(row.confidence), 0.99)
        row.source = f"{prior_source}|hu5-membership-continuity"
        row.source_hash = applied_membership_source_hash(decision, plan_id=plan_id)
        changes.append(
            {
                "membership_id": row.id,
                "security_id": row.security_id,
                "action": decision.action,
                "method": decision.method,
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "prior_source": prior_source,
                "source": row.source,
                "prior_source_hash": decision.prior_source_hash,
                "source_hash": row.source_hash,
                "decision_hash": decision.decision_hash,
                "evidence_ids": list(decision.evidence_ids),
            }
        )
    session.flush()
    return changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply a frozen HU-5 membership continuity plan.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--current-constituents-ref", required=True)
    parser.add_argument("--expected-plan-id", required=True)
    parser.add_argument("--expected-verify-count", type=int, required=True)
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
    decisions = validate_membership_continuity_projection(
        raw_payload,
        expected_plan_id=args.expected_plan_id,
        expected_current_source_ref=args.current_constituents_ref,
    )
    verify_count = sum(item.action == "verify" for item in decisions)
    reject_count = sum(item.action == "reject" for item in decisions)
    if verify_count != args.expected_verify_count or reject_count != args.expected_reject_count:
        raise RuntimeError(
            "actionable continuity decision counts changed: "
            f"verify={verify_count}, reject={reject_count}"
        )

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            changes = _stage(session, decisions, plan_id=args.expected_plan_id)
            session.commit()
    finally:
        engine.dispose()

    result = {
        "schema_version": MEMBERSHIP_CONTINUITY_APPLY_SCHEMA_VERSION,
        "mode": "apply",
        "plan_id": args.expected_plan_id,
        "applied_membership_updates": len(changes),
        "verified_updates": verify_count,
        "rejected_updates": reject_count,
        "changes": changes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "plan_id": args.expected_plan_id,
                "applied_membership_updates": len(changes),
                "verified_updates": verify_count,
                "rejected_updates": reject_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
