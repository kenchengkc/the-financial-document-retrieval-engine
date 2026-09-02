"""Project strict HU coverage after exact independent state corroboration.

The command is intentionally non-mutating.  It stages only fully-supported verification upgrades
inside one transaction, runs the existing HU-5 strict daily gate, writes an audit artifact, and
rolls the entire transaction back.
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
from fdre.research.hu5_universe import build_hu5_universe_gate, load_hu5_universe_records
from scripts.historical_universe_strict_coverage import load_provisional_membership_blockers


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _membership_symbol(blocker: object) -> str | None:
    identities = getattr(blocker, "identities")
    symbols = {normalize_symbol(item.symbol) for item in identities}
    return next(iter(symbols)) if len(symbols) == 1 else None


def _membership_intervals(blockers: tuple[object, ...]) -> tuple[
    tuple[ProvisionalStateInterval, ...], tuple[dict[str, object], ...]
]:
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


def _assert_row_matches(decision: StateSupportDecision, row: object) -> None:
    if getattr(row, "security_id") != decision.security_id:
        raise RuntimeError(f"stale {decision.row_kind} security_id for row {decision.row_id}")
    if getattr(row, "effective_from") != decision.effective_from:
        raise RuntimeError(f"stale {decision.row_kind} start for row {decision.row_id}")
    if getattr(row, "effective_to") != decision.effective_to:
        raise RuntimeError(f"stale {decision.row_kind} end for row {decision.row_id}")
    if getattr(row, "source_hash") != decision.source_hash:
        raise RuntimeError(f"stale {decision.row_kind} provenance for row {decision.row_id}")
    if getattr(row, "verification_status") != "provisional":
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
        model = UniverseMembership if decision.row_kind == "membership" else SecurityIdentityPeriod
        row = session.get(model, decision.row_id)
        if row is None:
            raise RuntimeError(f"missing {decision.row_kind} row {decision.row_id}")
        _assert_row_matches(decision, row)
        row.verification_status = "verified"
        row.confidence = max(float(row.confidence), 0.98)
        row.source = corroborated_source(str(row.source))
        row.source_hash = corroborated_source_hash(decision, plan_id=plan_id)
        if decision.row_kind == "membership":
            membership_updates += 1
        else:
            identity_updates += 1
    session.flush()
    return membership_updates, identity_updates


def _eligible_spans(gate: object) -> list[dict[str, object]]:
    dates = gate.dates
    spans: list[dict[str, object]] = []
    start: date | None = None
    previous: date | None = None
    for item in dates:
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
    return sorted(spans, key=lambda item: (-int(item["day_count"]), str(item["start"])))


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
    lineages = TickerMembershipLineageAdapter(
        source_ref=args.ticker_lineages_ref
    ).load(args.ticker_lineages)
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
            "error_counts": dict(sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))),
        },
        "decisions": [item.as_dict() for item in decisions],
        "interpretation": (
            "Projection only. Fully-supported rows are staged in one transaction using exact "
            "independent interval containment and then rolled back. Partial overlaps, ticker "
            "reuse ambiguity, missing state, and date-convention disagreements remain provisional."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
