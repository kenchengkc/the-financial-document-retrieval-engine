"""Project the reviewed final HU-5 identity adjudication in a rolled-back transaction."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe_identity_adjudication import (
    EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID,
    EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID,
    EXPECTED_RESIDUAL_SEC_PLAN_ID,
    EXPECTED_TOPOLOGY_AUDIT_ID,
    EXPECTED_TOPOLOGY_ID,
    IdentityAdjudicationCase,
    IdentityAnchor,
    MembershipAnchor,
    identity_adjudication_manifest_id,
    identity_adjudication_plan_id,
)
from fdre.research.historical_universe_identity_adjudication_apply import (
    APPLIED_SOURCE_SUFFIX,
    IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION,
    REVIEWED_SOURCE_OBSERVED_AT,
    applied_identity_source_hash,
)
from fdre.research.historical_universe_identity_adjudication_manifest import (
    build_hu5_identity_adjudication_cases,
)
from fdre.research.historical_universe_identity_strict_coverage import (
    IdentityStrictCoverageAudit,
    build_identity_strict_coverage_audit,
)
from fdre.research.historical_universe_membership_continuity import normalize_cik
from fdre.research.hu5_universe import (
    HU5UniverseGate,
    build_hu5_universe_gate,
    load_hu5_universe_records,
)
from scripts.research.historical_universe.historical_universe_identity_strict_coverage import (
    load_identity_coverage_memberships,
)
from scripts.research.historical_universe.historical_universe_identity_topology import (
    build_live_residual_identity_topology,
)

WINDOW_START = date(2010, 1, 1)
WINDOW_END = date(2026, 9, 1)
UNIVERSE_CODE = "sp500"
EXPECTED_DAY_COUNT = 6088
EXPECTED_PRE_STRICT_DAYS = 1426
EXPECTED_PRE_BLOCKED_DAYS = 4662


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _gate_payload(gate: HU5UniverseGate) -> dict[str, object]:
    return {
        "gate_manifest_id": gate.gate_manifest_id,
        "input_provenance_id": gate.input_provenance_id,
        "day_count": gate.day_count,
        "strict_eligible_day_count": gate.strict_eligible_day_count,
        "invalid_day_count": gate.invalid_day_count,
    }


def _audit_payload(audit: IdentityStrictCoverageAudit) -> dict[str, object]:
    return audit.as_dict()


def _require_pre_state(
    gate: HU5UniverseGate,
    audit: IdentityStrictCoverageAudit,
) -> None:
    expected_gate = {
        "day_count": EXPECTED_DAY_COUNT,
        "strict_eligible_day_count": EXPECTED_PRE_STRICT_DAYS,
        "invalid_day_count": EXPECTED_PRE_BLOCKED_DAYS,
    }
    actual_gate = {key: getattr(gate, key) for key in expected_gate}
    if actual_gate != expected_gate:
        raise RuntimeError(f"HU-5 pre-state gate drifted: {actual_gate}")
    expected_audit = {
        "audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
        "day_count": EXPECTED_DAY_COUNT,
        "strict_eligible_day_count": EXPECTED_PRE_STRICT_DAYS,
        "blocked_day_count": EXPECTED_PRE_BLOCKED_DAYS,
        "relevant_provisional_identity_count": 39,
    }
    audit_payload = audit.as_dict()
    actual_audit = {key: audit_payload.get(key) for key in expected_audit}
    if actual_audit != expected_audit:
        raise RuntimeError(f"identity-strict pre-state drifted: {actual_audit}")


def require_closed_post_state(
    gate: HU5UniverseGate,
    audit: IdentityStrictCoverageAudit,
) -> None:
    expected_gate = {
        "day_count": EXPECTED_DAY_COUNT,
        "strict_eligible_day_count": EXPECTED_DAY_COUNT,
        "invalid_day_count": 0,
    }
    actual_gate = {key: getattr(gate, key) for key in expected_gate}
    if actual_gate != expected_gate:
        raise RuntimeError(f"projected HU-5 gate failed: {actual_gate}")
    expected_audit = {
        "day_count": EXPECTED_DAY_COUNT,
        "strict_eligible_day_count": EXPECTED_DAY_COUNT,
        "blocked_day_count": 0,
        "provisional_membership_count": 0,
        "relevant_provisional_identity_count": 0,
    }
    audit_payload = audit.as_dict()
    actual_audit = {key: audit_payload.get(key) for key in expected_audit}
    if actual_audit != expected_audit:
        raise RuntimeError(f"projected identity-strict audit failed: {actual_audit}")


def _company_cik(session: Session, *, security_id: int) -> str:
    row = session.execute(
        select(Company.cik)
        .join(Security, Security.company_id == Company.id)
        .where(Security.id == security_id)
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"security {security_id} or its issuer disappeared")
    return normalize_cik(str(row.cik))


def _validate_membership_anchor(
    session: Session,
    anchor: MembershipAnchor,
) -> None:
    row = session.get(UniverseMembership, anchor.membership_id)
    if row is None:
        raise RuntimeError(f"membership anchor {anchor.membership_id} disappeared")
    actual = {
        "membership_id": row.id,
        "security_id": row.security_id,
        "cik": _company_cik(session, security_id=row.security_id),
        "universe_code": row.universe_code,
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "verification_status": row.verification_status,
        "source_hash": row.source_hash,
    }
    expected = {
        "membership_id": anchor.membership_id,
        "security_id": anchor.security_id,
        "cik": normalize_cik(anchor.cik),
        "universe_code": anchor.universe_code,
        "effective_from": anchor.effective_from,
        "effective_to": anchor.effective_to,
        "verification_status": anchor.verification_status,
        "source_hash": anchor.source_hash,
    }
    if actual != expected:
        raise RuntimeError(f"membership anchor {anchor.membership_id} drifted")


def _validate_identity_anchor(session: Session, anchor: IdentityAnchor) -> None:
    row = session.get(SecurityIdentityPeriod, anchor.identity_id)
    if row is None:
        raise RuntimeError(f"identity anchor {anchor.identity_id} disappeared")
    actual = {
        "identity_id": row.id,
        "security_id": row.security_id,
        "cik": _company_cik(session, security_id=row.security_id),
        "symbol": row.symbol,
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "verification_status": row.verification_status,
        "source_hash": row.source_hash,
    }
    expected = {
        "identity_id": anchor.identity_id,
        "security_id": anchor.security_id,
        "cik": normalize_cik(anchor.cik),
        "symbol": anchor.symbol,
        "effective_from": anchor.effective_from,
        "effective_to": anchor.effective_to,
        "verification_status": anchor.verification_status,
        "source_hash": anchor.source_hash,
    }
    if actual != expected:
        raise RuntimeError(f"identity anchor {anchor.identity_id} drifted")


def _live_existing_row(
    session: Session,
    case: IdentityAdjudicationCase,
) -> SecurityIdentityPeriod:
    if case.existing_identity_id is None:
        raise RuntimeError(f"case {case.case_id} does not reference an existing row")
    row = session.get(SecurityIdentityPeriod, case.existing_identity_id)
    if row is None:
        raise RuntimeError(f"identity row {case.existing_identity_id} disappeared")
    actual = {
        "security_id": row.security_id,
        "cik": _company_cik(session, security_id=row.security_id),
        "symbol": row.symbol,
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "source_hash": row.source_hash,
        "verification_status": row.verification_status,
    }
    expected = {
        "security_id": case.security_id,
        "cik": normalize_cik(case.cik),
        "symbol": case.symbol,
        "effective_from": case.prior_effective_from,
        "effective_to": case.prior_effective_to,
        "source_hash": case.prior_source_hash,
        "verification_status": case.prior_verification_status,
    }
    if actual != expected:
        raise RuntimeError(f"identity row {case.existing_identity_id} drifted")
    return row


def validate_live_identity_plan(
    session: Session,
    cases: tuple[IdentityAdjudicationCase, ...],
) -> dict[str, SecurityIdentityPeriod]:
    """Revalidate every row and frozen sibling before staging any mutation."""

    existing: dict[str, SecurityIdentityPeriod] = {}
    checked_identity_anchors: set[int] = set()
    checked_membership_anchors: set[int] = set()
    for case in cases:
        if _company_cik(session, security_id=case.security_id) != normalize_cik(case.cik):
            raise RuntimeError(f"case {case.case_id} issuer CIK drifted")
        if case.existing_identity_id is not None:
            existing[case.case_id] = _live_existing_row(session, case)
        for identity_anchor in case.identity_anchors:
            if identity_anchor.identity_id in checked_identity_anchors:
                continue
            _validate_identity_anchor(session, identity_anchor)
            checked_identity_anchors.add(identity_anchor.identity_id)
        for membership_anchor in case.membership_anchors:
            if membership_anchor.membership_id in checked_membership_anchors:
                continue
            _validate_membership_anchor(session, membership_anchor)
            checked_membership_anchors.add(membership_anchor.membership_id)
    return existing


def _overlapping_identities(
    session: Session,
    case: IdentityAdjudicationCase,
) -> tuple[SecurityIdentityPeriod, ...]:
    query = select(SecurityIdentityPeriod).where(
        SecurityIdentityPeriod.security_id == case.security_id,
        SecurityIdentityPeriod.verification_status != "rejected",
        (
            SecurityIdentityPeriod.effective_to.is_(None)
            | (SecurityIdentityPeriod.effective_to > case.target_effective_from)
        ),
    )
    if case.target_effective_to is not None:
        query = query.where(
            SecurityIdentityPeriod.effective_from < case.target_effective_to
        )
    return tuple(session.scalars(query.order_by(SecurityIdentityPeriod.id)))


def stage_identity_actions(
    session: Session,
    cases: tuple[IdentityAdjudicationCase, ...],
    *,
    manifest_id: str,
    plan_id: str,
    projection: bool,
) -> list[dict[str, object]]:
    """Stage all actions after a complete live-state check.

    Projection inserts use fixed negative IDs so PostgreSQL sequences are not advanced by
    the rolled-back read-only projection.
    """

    existing = validate_live_identity_plan(session, cases)
    changes: list[dict[str, object]] = []
    for case in cases:
        if case.action == "insert":
            continue
        row = existing[case.case_id]
        prior_source = str(row.source)
        row.effective_from = case.target_effective_from
        row.effective_to = case.target_effective_to
        row.verification_status = "verified"
        row.confidence = max(float(row.confidence), 0.99)
        row.source = f"{prior_source}|{APPLIED_SOURCE_SUFFIX}"
        row.source_observed_at = REVIEWED_SOURCE_OBSERVED_AT
        row.source_hash = applied_identity_source_hash(
            case,
            manifest_id=manifest_id,
            plan_id=plan_id,
        )
        changes.append(
            {
                "case_id": case.case_id,
                "action": case.action,
                "identity_id": row.id,
                "security_id": row.security_id,
                "symbol": row.symbol,
                "prior_effective_from": (
                    case.prior_effective_from.isoformat()
                    if case.prior_effective_from
                    else None
                ),
                "prior_effective_to": (
                    case.prior_effective_to.isoformat()
                    if case.prior_effective_to
                    else None
                ),
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "prior_source_hash": case.prior_source_hash,
                "source_hash": row.source_hash,
                "decision_hash": case.decision_hash,
            }
        )
    session.flush()

    insert_cases = tuple(item for item in cases if item.action == "insert")
    projection_ids = {
        case.case_id: -(index + 1)
        for index, case in enumerate(
            sorted(insert_cases, key=lambda item: item.case_id)
        )
    }
    for case in insert_cases:
        overlaps = _overlapping_identities(session, case)
        if overlaps:
            overlap_ids = [row.id for row in overlaps]
            raise RuntimeError(
                f"insert {case.case_id} overlaps live identities {overlap_ids}"
            )
        row = SecurityIdentityPeriod(
            id=projection_ids[case.case_id] if projection else None,
            security_id=case.security_id,
            symbol=case.symbol,
            name=case.name,
            exchange=case.exchange,
            effective_from=case.target_effective_from,
            effective_to=case.target_effective_to,
            source=APPLIED_SOURCE_SUFFIX,
            source_url=case.evidence[0].source_url,
            source_observed_at=REVIEWED_SOURCE_OBSERVED_AT,
            source_hash=applied_identity_source_hash(
                case,
                manifest_id=manifest_id,
                plan_id=plan_id,
            ),
            verification_status="verified",
            confidence=0.99,
        )
        session.add(row)
        session.flush()
        changes.append(
            {
                "case_id": case.case_id,
                "action": case.action,
                "identity_id": row.id if not projection else None,
                "projection_identity_id": row.id if projection else None,
                "security_id": row.security_id,
                "symbol": row.symbol,
                "prior_effective_from": None,
                "prior_effective_to": None,
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "prior_source_hash": None,
                "source_hash": row.source_hash,
                "decision_hash": case.decision_hash,
            }
        )
    session.flush()
    return sorted(changes, key=lambda item: str(item["case_id"]))


def _current_gate(session: Session) -> HU5UniverseGate:
    records = load_hu5_universe_records(
        session,
        universe_code=UNIVERSE_CODE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    return build_hu5_universe_gate(
        records,
        universe_code=UNIVERSE_CODE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )


def _current_identity_audit(session: Session) -> IdentityStrictCoverageAudit:
    memberships = load_identity_coverage_memberships(
        session,
        universe_code=UNIVERSE_CODE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    return build_identity_strict_coverage_audit(
        memberships,
        universe_code=UNIVERSE_CODE,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )


def _topology_payload(
    topology: Any,
    audit: IdentityStrictCoverageAudit,
) -> dict[str, object]:
    return {
        **topology.as_dict(),
        "universe_code": UNIVERSE_CODE,
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "strict_eligible_day_count": audit.strict_eligible_day_count,
        "blocked_day_count": audit.blocked_day_count,
    }


def project_identity_adjudication(
    session: Session,
    *,
    residual_sec: dict[str, Any],
) -> dict[str, object]:
    """Stage all 45 actions, prove both gates close, and always roll back."""

    try:
        topology, audit_before = build_live_residual_identity_topology(
            session,
            universe_code=UNIVERSE_CODE,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            expected_audit_id=EXPECTED_TOPOLOGY_AUDIT_ID,
        )
        topology_payload = _topology_payload(topology, audit_before)
        cases = build_hu5_identity_adjudication_cases(
            topology=topology_payload,
            residual_sec=residual_sec,
        )
        manifest_id = identity_adjudication_manifest_id(cases)
        plan_id = identity_adjudication_plan_id(cases, manifest_id=manifest_id)
        if manifest_id != EXPECTED_IDENTITY_ADJUDICATION_MANIFEST_ID:
            raise RuntimeError(f"identity adjudication manifest drifted: {manifest_id}")
        if plan_id != EXPECTED_IDENTITY_ADJUDICATION_PLAN_ID:
            raise RuntimeError(f"identity adjudication plan drifted: {plan_id}")
        action_counts = {
            action: Counter(item.action for item in cases)[action]
            for action in ("verify", "correct_and_verify", "insert")
        }

        gate_before = _current_gate(session)
        _require_pre_state(gate_before, audit_before)
        changes = stage_identity_actions(
            session,
            cases,
            manifest_id=manifest_id,
            plan_id=plan_id,
            projection=True,
        )
        gate_projected = _current_gate(session)
        audit_projected = _current_identity_audit(session)
        require_closed_post_state(gate_projected, audit_projected)

        reviewed_evidence = {
            item.evidence_id: item.as_dict()
            for case in cases
            for item in case.evidence
        }
        payload: dict[str, object] = {
            "schema_version": IDENTITY_ADJUDICATION_PROJECTION_SCHEMA_VERSION,
            "mode": "projection",
            "applied": False,
            "transaction_rolled_back": True,
            "frozen_audit_id": EXPECTED_TOPOLOGY_AUDIT_ID,
            "frozen_topology_id": EXPECTED_TOPOLOGY_ID,
            "frozen_residual_sec_plan_id": EXPECTED_RESIDUAL_SEC_PLAN_ID,
            "manifest_id": manifest_id,
            "plan_id": plan_id,
            "action_count": len(cases),
            "action_counts": action_counts,
            "decisions": [
                {**case.as_dict(), "decision_hash": case.decision_hash}
                for case in cases
            ],
            "reviewed_evidence": [
                reviewed_evidence[key] for key in sorted(reviewed_evidence)
            ],
            "changes": changes,
            "strict_coverage_before": _gate_payload(gate_before),
            "strict_coverage_projected": _gate_payload(gate_projected),
            "identity_strict_coverage_before": _audit_payload(audit_before),
            "identity_strict_coverage_projected": _audit_payload(audit_projected),
            "statement": (
                "All actions were staged in one transaction and both closure gates were "
                "recomputed from staged rows before that transaction was rolled back."
            ),
        }
        session.rollback()
        return payload
    except BaseException:
        session.rollback()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project the reviewed final HU-5 identity adjudication."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--residual-sec", type=Path, required=True)
    parser.add_argument("--universe-code", default=UNIVERSE_CODE)
    parser.add_argument("--window-start", type=_date, default=WINDOW_START)
    parser.add_argument("--window-end", type=_date, default=WINDOW_END)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.universe_code.strip().lower() != UNIVERSE_CODE:
        raise RuntimeError(f"final adjudication is frozen to universe {UNIVERSE_CODE}")
    if args.window_start != WINDOW_START or args.window_end != WINDOW_END:
        raise RuntimeError(
            "final adjudication window must remain "
            f"{WINDOW_START.isoformat()} through {WINDOW_END.isoformat()}"
        )
    residual_sec = json.loads(args.residual_sec.read_text(encoding="utf-8"))
    if not isinstance(residual_sec, dict):
        raise RuntimeError("residual SEC artifact root must be an object")

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            payload = project_identity_adjudication(
                session,
                residual_sec=residual_sec,
            )
    finally:
        engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest_id": payload["manifest_id"],
                "plan_id": payload["plan_id"],
                "action_count": payload["action_count"],
                "action_counts": payload["action_counts"],
                "strict_eligible_day_count": EXPECTED_DAY_COUNT,
                "blocked_day_count": 0,
                "transaction_rolled_back": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
