"""Project exact live topology for residual HU-5 identity-aware coverage blockers.

The command is read-only. It first rebuilds the identity-aware strict-coverage audit, then exposes
only the securities that actually block that audit: relevant provisional identity periods and
identity-missing gaps.  For each blocker it includes every same-security identity period, every
same-universe membership period, immutable row/source hashes, and persisted SEC promotion evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityEvidence,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe_identity_topology import (
    IdentityTopologyEvidence,
    IdentityTopologyPeriod,
    MembershipTopologyPeriod,
    ResidualIdentityGap,
    ResidualIdentityTarget,
    build_residual_identity_topology,
)
from scripts.research.historical_universe.historical_universe_identity_strict_coverage import (
    load_identity_coverage_memberships,
)
from fdre.research.historical_universe_identity_strict_coverage import (
    build_identity_strict_coverage_audit,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _timestamp(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    if not callable(isoformat):
        raise RuntimeError(f"expected datetime-like value, got {type(value).__name__}")
    return str(isoformat())


def _load_security_ciks(session: Session, security_ids: tuple[int, ...]) -> dict[int, str]:
    if not security_ids:
        return {}
    rows = session.execute(
        select(Security.id, Company.cik)
        .join(Company, Company.id == Security.company_id)
        .where(Security.id.in_(security_ids))
        .order_by(Security.id)
    ).all()
    result = {int(row.id): str(row.cik) for row in rows}
    if set(result) != set(security_ids):
        missing = sorted(set(security_ids) - set(result))
        raise RuntimeError(f"missing company/CIK bindings for securities {missing}")
    return result


def _load_evidence(
    session: Session,
    identity_ids: tuple[int, ...],
) -> dict[int, tuple[IdentityTopologyEvidence, ...]]:
    if not identity_ids:
        return {}
    rows = session.execute(
        select(
            SecurityIdentityEvidence.security_identity_period_id,
            SecurityIdentityEvidence.evidence_id,
            SecurityIdentityEvidence.cik,
            SecurityIdentityEvidence.symbol,
            SecurityIdentityEvidence.accession_number,
            SecurityIdentityEvidence.filing_date,
            SecurityIdentityEvidence.form_type,
            SecurityIdentityEvidence.concept_name,
            SecurityIdentityEvidence.context_ref,
            SecurityIdentityEvidence.source_url,
            SecurityIdentityEvidence.payload_sha256,
            SecurityIdentityEvidence.decision_hash,
            SecurityIdentityEvidence.state_decision_hash,
            SecurityIdentityEvidence.state_lineage_id,
            SecurityIdentityEvidence.projection_plan_id,
        )
        .where(SecurityIdentityEvidence.security_identity_period_id.in_(identity_ids))
        .order_by(
            SecurityIdentityEvidence.security_identity_period_id,
            SecurityIdentityEvidence.filing_date,
            SecurityIdentityEvidence.accession_number,
            SecurityIdentityEvidence.evidence_id,
        )
    ).all()
    grouped: dict[int, list[IdentityTopologyEvidence]] = defaultdict(list)
    for row in rows:
        grouped[int(row.security_identity_period_id)].append(
            IdentityTopologyEvidence(
                evidence_id=str(row.evidence_id),
                cik=str(row.cik),
                symbol=str(row.symbol),
                accession_number=str(row.accession_number),
                filing_date=row.filing_date.isoformat(),
                form_type=str(row.form_type),
                concept_name=str(row.concept_name),
                context_ref=str(row.context_ref) if row.context_ref is not None else None,
                source_url=str(row.source_url),
                payload_sha256=str(row.payload_sha256),
                decision_hash=str(row.decision_hash),
                state_decision_hash=str(row.state_decision_hash),
                state_lineage_id=str(row.state_lineage_id),
                projection_plan_id=str(row.projection_plan_id),
            )
        )
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _load_identity_periods(
    session: Session,
    security_ids: tuple[int, ...],
) -> dict[int, tuple[IdentityTopologyPeriod, ...]]:
    if not security_ids:
        return {}
    rows = session.execute(
        select(
            SecurityIdentityPeriod.id,
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.name,
            SecurityIdentityPeriod.exchange,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.verification_status,
            SecurityIdentityPeriod.source,
            SecurityIdentityPeriod.source_url,
            SecurityIdentityPeriod.source_observed_at,
            SecurityIdentityPeriod.source_hash,
            SecurityIdentityPeriod.confidence,
        )
        .where(SecurityIdentityPeriod.security_id.in_(security_ids))
        .order_by(
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.id,
        )
    ).all()
    identity_ids = tuple(int(row.id) for row in rows)
    evidence_by_identity = _load_evidence(session, identity_ids)
    grouped: dict[int, list[IdentityTopologyPeriod]] = defaultdict(list)
    for row in rows:
        identity_id = int(row.id)
        security_id = int(row.security_id)
        grouped[security_id].append(
            IdentityTopologyPeriod(
                identity_id=identity_id,
                security_id=security_id,
                symbol=str(row.symbol),
                name=str(row.name) if row.name is not None else None,
                exchange=str(row.exchange) if row.exchange is not None else None,
                effective_from=row.effective_from.isoformat(),
                effective_to=row.effective_to.isoformat() if row.effective_to else None,
                verification_status=str(row.verification_status),
                source=str(row.source),
                source_url=str(row.source_url) if row.source_url is not None else None,
                source_observed_at=_timestamp(row.source_observed_at),
                source_hash=str(row.source_hash),
                confidence=float(row.confidence),
                evidence=evidence_by_identity.get(identity_id, ()),
            )
        )
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _load_memberships(
    session: Session,
    security_ids: tuple[int, ...],
    *,
    universe_code: str,
) -> dict[int, tuple[MembershipTopologyPeriod, ...]]:
    if not security_ids:
        return {}
    rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.universe_code,
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.verification_status,
            UniverseMembership.source,
            UniverseMembership.source_url,
            UniverseMembership.source_observed_at,
            UniverseMembership.source_hash,
            UniverseMembership.confidence,
        )
        .where(
            UniverseMembership.security_id.in_(security_ids),
            UniverseMembership.universe_code == universe_code,
        )
        .order_by(
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.id,
        )
    ).all()
    grouped: dict[int, list[MembershipTopologyPeriod]] = defaultdict(list)
    for row in rows:
        security_id = int(row.security_id)
        grouped[security_id].append(
            MembershipTopologyPeriod(
                membership_id=int(row.id),
                universe_code=str(row.universe_code),
                security_id=security_id,
                effective_from=row.effective_from.isoformat(),
                effective_to=row.effective_to.isoformat() if row.effective_to else None,
                verification_status=str(row.verification_status),
                source=str(row.source),
                source_url=str(row.source_url) if row.source_url is not None else None,
                source_observed_at=_timestamp(row.source_observed_at),
                source_hash=str(row.source_hash),
                confidence=float(row.confidence),
            )
        )
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project exact topology for residual HU-5 identity blockers."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--expected-audit-id")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    universe_code = args.universe_code.strip().lower()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            coverage_memberships = load_identity_coverage_memberships(
                session,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            audit = build_identity_strict_coverage_audit(
                coverage_memberships,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            if args.expected_audit_id and audit.audit_id != args.expected_audit_id:
                raise RuntimeError(
                    "identity-aware audit drift: "
                    f"expected {args.expected_audit_id}, got {audit.audit_id}"
                )

            relevant_ids = audit.relevant_provisional_identity_ids
            identity_issue_memberships: dict[int, set[int]] = defaultdict(set)
            gap_issues = []
            for issue in audit.issues:
                if issue.reason == "identity_not_verified":
                    if len(issue.active_identity_ids) != 1:
                        raise RuntimeError(
                            "identity_not_verified issue must contain exactly one active identity"
                        )
                    identity_issue_memberships[issue.active_identity_ids[0]].add(
                        issue.membership_id
                    )
                elif issue.reason == "identity_missing":
                    gap_issues.append(issue)

            if tuple(sorted(identity_issue_memberships)) != relevant_ids:
                raise RuntimeError(
                    "identity-aware audit relevant ID summary does not match blocker issues"
                )

            target_rows = session.execute(
                select(
                    SecurityIdentityPeriod.id,
                    SecurityIdentityPeriod.security_id,
                    SecurityIdentityPeriod.symbol,
                    SecurityIdentityPeriod.effective_from,
                    SecurityIdentityPeriod.effective_to,
                    SecurityIdentityPeriod.source_hash,
                )
                .where(SecurityIdentityPeriod.id.in_(relevant_ids))
                .order_by(SecurityIdentityPeriod.id)
            ).all()
            if len(target_rows) != len(relevant_ids):
                raise RuntimeError("one or more relevant provisional identity rows disappeared")

            security_ids = tuple(
                sorted(
                    {int(row.security_id) for row in target_rows}
                    | {int(issue.security_id) for issue in gap_issues}
                )
            )
            ciks = _load_security_ciks(session, security_ids)
            identities = _load_identity_periods(session, security_ids)
            memberships = _load_memberships(
                session,
                security_ids,
                universe_code=universe_code,
            )

            targets = tuple(
                ResidualIdentityTarget(
                    identity_id=int(row.id),
                    security_id=int(row.security_id),
                    cik=ciks[int(row.security_id)],
                    symbol=str(row.symbol),
                    effective_from=row.effective_from.isoformat(),
                    effective_to=row.effective_to.isoformat() if row.effective_to else None,
                    source_hash=str(row.source_hash),
                    issue_membership_ids=tuple(
                        sorted(identity_issue_memberships[int(row.id)])
                    ),
                    identity_periods=identities.get(int(row.security_id), ()),
                    memberships=memberships.get(int(row.security_id), ()),
                )
                for row in target_rows
            )
            gaps = tuple(
                ResidualIdentityGap(
                    membership_id=issue.membership_id,
                    security_id=issue.security_id,
                    cik=ciks[issue.security_id],
                    effective_from=issue.effective_from.isoformat(),
                    effective_to=issue.effective_to.isoformat(),
                    identity_periods=identities.get(issue.security_id, ()),
                    memberships=memberships.get(issue.security_id, ()),
                )
                for issue in gap_issues
            )
            topology = build_residual_identity_topology(
                audit_id=audit.audit_id,
                targets=targets,
                gaps=gaps,
            )
            session.rollback()
    finally:
        engine.dispose()

    payload = {
        **topology.as_dict(),
        "universe_code": universe_code,
        "window_start": args.window_start.isoformat(),
        "window_end": args.window_end.isoformat(),
        "strict_eligible_day_count": audit.strict_eligible_day_count,
        "blocked_day_count": audit.blocked_day_count,
        "interpretation": (
            "Read-only residual identity topology. Rows and gaps are selected exclusively from the "
            "identity-aware strict-coverage audit; same-security neighboring identity and membership "
            "periods are context, not automatic evidence for promotion or boundary propagation."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "audit_id": topology.audit_id,
                "topology_id": topology.topology_id,
                "target_count": len(topology.targets),
                "gap_count": len(topology.gaps),
                "blocked_day_count": audit.blocked_day_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
