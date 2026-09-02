"""Project strict HU coverage after exact independent state corroboration.

The command is intentionally non-mutating. It stages only fully-supported verification upgrades
inside one transaction, runs the existing HU-5 strict daily gate, writes an audit artifact, and
rolls the entire transaction back.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
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
    UniverseMembershipEvidence,
)
from fdre.research.historical_universe_lineage import (
    TickerMembershipLineageAdapter,
    normalize_symbol,
)
from fdre.research.historical_universe_state_support import (
    ProvisionalStateInterval,
    StateSupportDecision,
    corroborated_source,
    corroborated_source_hash,
    plan_state_support,
    state_support_plan_id,
)
from fdre.research.historical_universe_strict_coverage import ProvisionalMembershipBlocker
from fdre.research.hu5_universe import (
    HU5UniverseGate,
    build_hu5_universe_gate,
    load_hu5_universe_records,
)
from scripts.historical_universe_strict_coverage import load_provisional_membership_blockers


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _membership_symbol(blocker: ProvisionalMembershipBlocker) -> str | None:
    symbols = {normalize_symbol(item.symbol) for item in blocker.identities}
    return next(iter(symbols)) if len(symbols) == 1 else None


def _membership_intervals(
    blockers: tuple[ProvisionalMembershipBlocker, ...],
) -> tuple[tuple[ProvisionalStateInterval, ...], tuple[dict[str, object], ...]]:
    intervals: list[ProvisionalStateInterval] = []
    excluded: list[dict[str, object]] = []
    for blocker in blockers:
        symbol = _membership_symbol(blocker)
        if symbol is None:
            excluded.append(
                {
                    "row_kind": "membership",
                    "row_id": blocker.membership_id,
                    "security_id": blocker.security_id,
                    "cik": blocker.cik,
                    "reason": "membership does not resolve to exactly one exact identity symbol",
                    "symbols": sorted({item.symbol for item in blocker.identities}),
                }
            )
            continue
        intervals.append(
            ProvisionalStateInterval(
                row_kind="membership",
                row_id=blocker.membership_id,
                security_id=blocker.security_id,
                cik=blocker.cik,
                symbol=symbol,
                effective_from=blocker.effective_from,
                effective_to=blocker.effective_to,
                source=blocker.source,
                source_hash=blocker.source_hash,
            )
        )
    return tuple(intervals), tuple(excluded)


def _provisional_identity_intervals(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> tuple[ProvisionalStateInterval, ...]:
    security_ids = tuple(
        sorted(
            {
                int(value)
                for value in session.scalars(
                    select(UniverseMembership.security_id).where(
                        UniverseMembership.universe_code == universe_code,
                        UniverseMembership.verification_status != "rejected",
                        UniverseMembership.effective_from <= window_end,
                        (
                            UniverseMembership.effective_to.is_(None)
                            | (UniverseMembership.effective_to > window_start)
                        ),
                    )
                )
            }
        )
    )
    if not security_ids:
        return ()
    rows = session.execute(
        select(
            SecurityIdentityPeriod.id,
            SecurityIdentityPeriod.security_id,
            Company.cik,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.source,
            SecurityIdentityPeriod.source_hash,
        )
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            SecurityIdentityPeriod.security_id.in_(security_ids),
            SecurityIdentityPeriod.verification_status == "provisional",
            SecurityIdentityPeriod.effective_from <= window_end,
            (
                SecurityIdentityPeriod.effective_to.is_(None)
                | (SecurityIdentityPeriod.effective_to > window_start)
            ),
        )
        .order_by(
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.id,
        )
    ).all()
    return tuple(
        ProvisionalStateInterval(
            row_kind="identity",
            row_id=int(row.id),
            security_id=int(row.security_id),
            cik=str(row.cik),
            symbol=normalize_symbol(str(row.symbol)),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source=str(row.source),
            source_hash=str(row.source_hash),
        )
        for row in rows
    )


def _residual_membership_evidence(
    session: Session,
    decisions: tuple[StateSupportDecision, ...],
    *,
    universe_code: str,
) -> dict[str, list[dict[str, object]]]:
    symbols = {
        item.symbol
        for item in decisions
        if item.row_kind == "membership" and not item.promotable
    }
    if not symbols:
        return {}
    rows = session.execute(
        select(
            UniverseMembershipEvidence.evidence_id,
            UniverseMembershipEvidence.event_type,
            UniverseMembershipEvidence.effective_at,
            UniverseMembershipEvidence.announced_at,
            UniverseMembershipEvidence.effective_session,
            UniverseMembershipEvidence.raw_symbol,
            UniverseMembershipEvidence.raw_name,
            UniverseMembershipEvidence.raw_cik,
            UniverseMembershipEvidence.source,
            UniverseMembershipEvidence.source_url,
            UniverseMembershipEvidence.source_record_id,
            UniverseMembershipEvidence.source_record_hash,
        )
        .where(UniverseMembershipEvidence.universe_code == universe_code)
        .order_by(
            UniverseMembershipEvidence.effective_at,
            UniverseMembershipEvidence.source,
            UniverseMembershipEvidence.evidence_id,
        )
    ).all()
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        symbol = normalize_symbol(str(row.raw_symbol))
        if symbol not in symbols:
            continue
        grouped[symbol].append(
            {
                "evidence_id": str(row.evidence_id),
                "event_type": str(row.event_type),
                "effective_at": row.effective_at.isoformat(),
                "announced_at": row.announced_at.isoformat() if row.announced_at else None,
                "effective_session": str(row.effective_session),
                "raw_symbol": str(row.raw_symbol),
                "raw_name": str(row.raw_name) if row.raw_name is not None else None,
                "raw_cik": str(row.raw_cik) if row.raw_cik is not None else None,
                "source": str(row.source),
                "source_url": str(row.source_url) if row.source_url is not None else None,
                "source_record_id": (
                    str(row.source_record_id) if row.source_record_id is not None else None
                ),
                "source_record_hash": str(row.source_record_hash),
            }
        )
    return dict(sorted(grouped.items()))


def _assert_row_matches(
    decision: StateSupportDecision,
    row: UniverseMembership | SecurityIdentityPeriod,
) -> None:
    if row.security_id != decision.security_id:
        raise RuntimeError(f"stale {decision.row_kind} security_id for row {decision.row_id}")
    if row.effective_from != decision.effective_from:
        raise RuntimeError(f"stale {decision.row_kind} start for row {decision.row_id}")
    if row.effective_to != decision.effective_to:
        raise RuntimeError(f"stale {decision.row_kind} end for row {decision.row_id}")
    if row.source_hash != decision.source_hash:
        raise RuntimeError(f"stale {decision.row_kind} provenance for row {decision.row_id}")
    if row.verification_status != "provisional":
        raise RuntimeError(f"row {decision.row_kind}/{decision.row_id} is no longer provisional")


def _stage_decisions(
    session: Session,
    decisions: tuple[StateSupportDecision, ...],
    *,
    plan_id: str,
) -> tuple[int, int]:
    membership_updates = 0
    identity_updates = 0
    for decision in decisions:
        if not decision.promotable:
            continue
        if decision.row_kind == "membership":
            membership = session.get(UniverseMembership, decision.row_id)
            if membership is None:
                raise RuntimeError(f"missing membership row {decision.row_id}")
            _assert_row_matches(decision, membership)
            membership.verification_status = "verified"
            membership.confidence = max(float(membership.confidence), 0.98)
            membership.source = corroborated_source(str(membership.source))
            membership.source_hash = corroborated_source_hash(decision, plan_id=plan_id)
            membership_updates += 1
        else:
            identity = session.get(SecurityIdentityPeriod, decision.row_id)
            if identity is None:
                raise RuntimeError(f"missing identity row {decision.row_id}")
            _assert_row_matches(decision, identity)
            identity.verification_status = "verified"
            identity.confidence = max(float(identity.confidence), 0.98)
            identity.source = corroborated_source(str(identity.source))
            identity.source_hash = corroborated_source_hash(decision, plan_id=plan_id)
            identity_updates += 1
    session.flush()
    return membership_updates, identity_updates


def _eligible_spans(gate: HU5UniverseGate) -> list[dict[str, str | int]]:
    spans: list[dict[str, str | int]] = []
    start: date | None = None
    previous: date | None = None
    for item in gate.dates:
        current = date.fromisoformat(item.as_of)
        if item.eligible:
            if start is None:
                start = current
            previous = current
        elif start is not None and previous is not None:
            spans.append(
                {
                    "start": start.isoformat(),
                    "end": previous.isoformat(),
                    "day_count": (previous - start).days + 1,
                }
            )
            start = None
            previous = None
    if start is not None and previous is not None:
        spans.append(
            {
                "start": start.isoformat(),
                "end": previous.isoformat(),
                "day_count": (previous - start).days + 1,
            }
        )
    return sorted(
        spans,
        key=lambda item: (-int(item["day_count"]), str(item["start"])),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project exact state-corroboration coverage.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--ticker-lineages", type=Path, required=True)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    universe_code = args.universe_code.strip().lower()
    lineages = TickerMembershipLineageAdapter(source_ref=args.ticker_lineages_ref).load(
        args.ticker_lineages
    )
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            membership_blockers = load_provisional_membership_blockers(
                session,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            membership_intervals, excluded_memberships = _membership_intervals(
                membership_blockers
            )
            identity_intervals = _provisional_identity_intervals(
                session,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            decisions = plan_state_support(
                membership_intervals + identity_intervals,
                lineages,
            )
            residual_evidence = _residual_membership_evidence(
                session,
                decisions,
                universe_code=universe_code,
            )
            plan_id = state_support_plan_id(decisions)
            membership_updates, identity_updates = _stage_decisions(
                session,
                decisions,
                plan_id=plan_id,
            )
            records = load_hu5_universe_records(
                session,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            gate = build_hu5_universe_gate(
                records,
                universe_code=universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            error_counts = Counter(
                item.error for item in gate.dates if not item.eligible and item.error is not None
            )
            session.rollback()
    finally:
        engine.dispose()

    status_counts = Counter(item.status for item in decisions)
    membership_status_counts = Counter(
        item.status for item in decisions if item.row_kind == "membership"
    )
    identity_status_counts = Counter(
        item.status for item in decisions if item.row_kind == "identity"
    )
    payload = {
        "schema_version": "fdre-hu-state-support-projection-v1",
        "plan_id": plan_id,
        "universe_code": universe_code,
        "window_start": args.window_start.isoformat(),
        "window_end": args.window_end.isoformat(),
        "ticker_lineages_ref": args.ticker_lineages_ref,
        "ticker_lineage_count": len(lineages),
        "membership_blocker_count": len(membership_blockers),
        "provisional_identity_count": len(identity_intervals),
        "excluded_memberships": list(excluded_memberships),
        "status_counts": dict(sorted(status_counts.items())),
        "membership_status_counts": dict(sorted(membership_status_counts.items())),
        "identity_status_counts": dict(sorted(identity_status_counts.items())),
        "projected_membership_updates": membership_updates,
        "projected_identity_updates": identity_updates,
        "projected_gate": {
            "gate_manifest_id": gate.gate_manifest_id,
            "input_provenance_id": gate.input_provenance_id,
            "day_count": gate.day_count,
            "strict_eligible_day_count": gate.strict_eligible_day_count,
            "invalid_day_count": gate.invalid_day_count,
            "eligible_spans": _eligible_spans(gate),
            "error_counts": dict(
                sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))
            ),
        },
        "residual_membership_evidence": residual_evidence,
        "decisions": [item.as_dict() for item in decisions],
        "interpretation": (
            "Projection only. Fully-supported rows are staged in one transaction using exact "
            "independent interval containment and then rolled back. Partial overlaps, ticker "
            "reuse ambiguity, missing state, and date-convention disagreements remain provisional."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
