"""Audit final HU-5 coverage including point-in-time security identities."""

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
from fdre.research.historical_universe_identity_strict_coverage import (
    IdentityCoverageIdentity,
    IdentityCoverageMembership,
    build_identity_strict_coverage_audit,
)


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _overlaps(
    start: date,
    end: date | None,
    *,
    other_start: date,
    other_end: date | None,
) -> bool:
    return (other_end is None or start < other_end) and (end is None or other_start < end)


def load_identity_coverage_memberships(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> tuple[IdentityCoverageMembership, ...]:
    normalized = universe_code.strip().lower()
    membership_rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.security_id,
            Company.cik,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.verification_status,
            UniverseMembership.source_hash,
        )
        .join(Security, Security.id == UniverseMembership.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            UniverseMembership.universe_code == normalized,
            UniverseMembership.verification_status != "rejected",
            UniverseMembership.effective_from <= window_end,
            (
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > window_start)
            ),
        )
        .order_by(UniverseMembership.id)
    ).all()
    security_ids = sorted({int(row.security_id) for row in membership_rows})
    identity_rows = (
        session.execute(
            select(
                SecurityIdentityPeriod.id,
                SecurityIdentityPeriod.security_id,
                SecurityIdentityPeriod.symbol,
                SecurityIdentityPeriod.effective_from,
                SecurityIdentityPeriod.effective_to,
                SecurityIdentityPeriod.verification_status,
                SecurityIdentityPeriod.source_hash,
            )
            .where(
                SecurityIdentityPeriod.security_id.in_(security_ids),
                SecurityIdentityPeriod.verification_status != "rejected",
                SecurityIdentityPeriod.effective_from <= window_end,
                (
                    SecurityIdentityPeriod.effective_to.is_(None)
                    | (SecurityIdentityPeriod.effective_to > window_start)
                ),
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
    identities_by_security: dict[int, list[IdentityCoverageIdentity]] = defaultdict(list)
    for row in identity_rows:
        identities_by_security[int(row.security_id)].append(
            IdentityCoverageIdentity(
                identity_id=int(row.id),
                symbol=str(row.symbol),
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                verification_status=str(row.verification_status),
                source_hash=str(row.source_hash),
            )
        )

    memberships: list[IdentityCoverageMembership] = []
    for row in membership_rows:
        membership_start = row.effective_from
        membership_end = row.effective_to
        identities = tuple(
            identity
            for identity in identities_by_security[int(row.security_id)]
            if _overlaps(
                identity.effective_from,
                identity.effective_to,
                other_start=membership_start,
                other_end=membership_end,
            )
        )
        memberships.append(
            IdentityCoverageMembership(
                membership_id=int(row.id),
                security_id=int(row.security_id),
                cik=str(row.cik),
                effective_from=membership_start,
                effective_to=membership_end,
                verification_status=str(row.verification_status),
                source_hash=str(row.source_hash),
                identities=identities,
            )
        )
    return tuple(memberships)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit historical-universe membership and identity strict coverage."
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
            memberships = load_identity_coverage_memberships(
                session,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            audit = build_identity_strict_coverage_audit(
                memberships,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            session.rollback()
    finally:
        engine.dispose()

    payload = audit.as_dict()
    payload["interpretation"] = (
        "A date is strict-eligible only when every active non-rejected membership is verified "
        "and each member security has exactly one active non-rejected verified identity."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
