"""Audit the exact provisional memberships blocking strict historical-universe dates."""

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
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe_strict_coverage import (
    IdentityContext,
    ProvisionalMembershipBlocker,
    build_strict_coverage_audit,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _overlaps(
    start: date,
    end: date | None,
    *,
    window_start: date,
    window_end: date,
) -> bool:
    return start <= window_end and (end is None or window_start < end)


def load_provisional_membership_blockers(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> tuple[ProvisionalMembershipBlocker, ...]:
    normalized = universe_code.strip().lower()
    rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.security_id,
            Company.cik,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.source,
            UniverseMembership.source_url,
            UniverseMembership.source_hash,
            UniverseMembership.confidence,
        )
        .join(Security, Security.id == UniverseMembership.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            UniverseMembership.universe_code == normalized,
            UniverseMembership.verification_status == "provisional",
            UniverseMembership.effective_from <= window_end,
            (
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > window_start)
            ),
        )
        .order_by(
            UniverseMembership.effective_from,
            UniverseMembership.security_id,
            UniverseMembership.id,
        )
    ).all()
    security_ids = sorted({int(membership_row.security_id) for membership_row in rows})
    identity_rows = (
        session.execute(
            select(
                SecurityIdentityPeriod.security_id,
                SecurityIdentityPeriod.symbol,
                SecurityIdentityPeriod.effective_from,
                SecurityIdentityPeriod.effective_to,
                SecurityIdentityPeriod.verification_status,
                SecurityIdentityPeriod.source_hash,
            )
            .where(
                SecurityIdentityPeriod.security_id.in_(security_ids),
                SecurityIdentityPeriod.effective_from <= window_end,
                (
                    SecurityIdentityPeriod.effective_to.is_(None)
                    | (SecurityIdentityPeriod.effective_to > window_start)
                ),
                SecurityIdentityPeriod.verification_status != "rejected",
            )
            .order_by(
                SecurityIdentityPeriod.security_id,
                SecurityIdentityPeriod.effective_from,
                SecurityIdentityPeriod.id,
            )
        ).all()
        if security_ids
        else []
    )
    identities_by_security: dict[int, list[IdentityContext]] = defaultdict(list)
    for identity_row in identity_rows:
        identities_by_security[int(identity_row.security_id)].append(
            IdentityContext(
                symbol=str(identity_row.symbol),
                effective_from=identity_row.effective_from,
                effective_to=identity_row.effective_to,
                verification_status=str(identity_row.verification_status),
                source_hash=str(identity_row.source_hash),
            )
        )

    blockers: list[ProvisionalMembershipBlocker] = []
    for membership_row in rows:
        identities = tuple(
            identity
            for identity in identities_by_security[int(membership_row.security_id)]
            if _overlaps(
                identity.effective_from,
                identity.effective_to,
                window_start=membership_row.effective_from,
                window_end=membership_row.effective_to or window_end,
            )
        )
        blockers.append(
            ProvisionalMembershipBlocker(
                membership_id=int(membership_row.id),
                security_id=int(membership_row.security_id),
                cik=str(membership_row.cik),
                effective_from=membership_row.effective_from,
                effective_to=membership_row.effective_to,
                source=str(membership_row.source),
                source_url=(
                    str(membership_row.source_url)
                    if membership_row.source_url is not None
                    else None
                ),
                source_hash=str(membership_row.source_hash),
                confidence=float(membership_row.confidence),
                identities=identities,
            )
        )
    return tuple(blockers)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit strict historical-universe blockers.")
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
            audit = build_strict_coverage_audit(
                blockers,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            session.rollback()
    finally:
        engine.dispose()

    payload = audit.as_dict()
    payload["interpretation"] = (
        "This is a read-only inventory of provisional membership intervals that make a complete "
        "strict snapshot invalid. It does not omit affected constituents, opt into provisional "
        "evidence, or mutate production state. The greedy cover ranks remediation leverage only; "
        "it is not permission to promote a row without independent evidence."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
