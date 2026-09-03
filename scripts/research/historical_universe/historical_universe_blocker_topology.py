"""Read-only production topology for HU-5 provisional membership blockers.

For each issuer touched by a live provisional membership in the requested window, emit every
sibling Security plus its overlapping identity and membership intervals.  The report exists to
separate genuine multi-class securities from accidental ticker-transition splits before any
structural remediation is attempted.  It never mutates the database.
"""

from __future__ import annotations

import argparse
import hashlib
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

_SCHEMA_VERSION = "fdre-hu5-blocker-topology-v1"


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_report(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> dict[str, object]:
    normalized = universe_code.strip().lower()
    blocker_rows = session.execute(
        select(
            UniverseMembership.id,
            UniverseMembership.security_id,
            Security.company_id,
            Company.cik,
        )
        .join(Security, Security.id == UniverseMembership.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            UniverseMembership.universe_code == normalized,
            UniverseMembership.verification_status == "provisional",
            UniverseMembership.effective_from <= window_end,
            UniverseMembership.effective_to.is_(None)
            | (UniverseMembership.effective_to > window_start),
        )
        .order_by(UniverseMembership.id)
    ).all()
    blocker_ids = {int(row.id) for row in blocker_rows}
    company_ids = sorted({int(row.company_id) for row in blocker_rows})

    securities = (
        session.execute(
            select(
                Security.id,
                Security.company_id,
                Security.security_type,
                Security.share_class,
                Company.cik,
                Company.name,
            )
            .join(Company, Company.id == Security.company_id)
            .where(Security.company_id.in_(company_ids))
            .order_by(Company.cik, Security.id)
        ).all()
        if company_ids
        else []
    )
    security_ids = sorted({int(row.id) for row in securities})

    identities = (
        session.execute(
            select(
                SecurityIdentityPeriod.id,
                SecurityIdentityPeriod.security_id,
                SecurityIdentityPeriod.symbol,
                SecurityIdentityPeriod.name,
                SecurityIdentityPeriod.effective_from,
                SecurityIdentityPeriod.effective_to,
                SecurityIdentityPeriod.verification_status,
                SecurityIdentityPeriod.confidence,
                SecurityIdentityPeriod.source,
                SecurityIdentityPeriod.source_hash,
            )
            .where(
                SecurityIdentityPeriod.security_id.in_(security_ids),
                SecurityIdentityPeriod.effective_from <= window_end,
                SecurityIdentityPeriod.effective_to.is_(None)
                | (SecurityIdentityPeriod.effective_to > window_start),
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
    memberships = (
        session.execute(
            select(
                UniverseMembership.id,
                UniverseMembership.security_id,
                UniverseMembership.universe_code,
                UniverseMembership.effective_from,
                UniverseMembership.effective_to,
                UniverseMembership.verification_status,
                UniverseMembership.confidence,
                UniverseMembership.source,
                UniverseMembership.source_url,
                UniverseMembership.source_hash,
            )
            .where(
                UniverseMembership.security_id.in_(security_ids),
                UniverseMembership.universe_code == normalized,
                UniverseMembership.effective_from <= window_end,
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > window_start),
            )
            .order_by(
                UniverseMembership.security_id,
                UniverseMembership.effective_from,
                UniverseMembership.id,
            )
        ).all()
        if security_ids
        else []
    )

    identities_by_security: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in identities:
        identities_by_security[int(row.security_id)].append(
            {
                "identity_id": int(row.id),
                "symbol": str(row.symbol),
                "name": str(row.name) if row.name is not None else None,
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "verification_status": str(row.verification_status),
                "confidence": float(row.confidence),
                "source": str(row.source),
                "source_hash": str(row.source_hash),
            }
        )

    memberships_by_security: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in memberships:
        memberships_by_security[int(row.security_id)].append(
            {
                "membership_id": int(row.id),
                "blocking_provisional": int(row.id) in blocker_ids,
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "verification_status": str(row.verification_status),
                "confidence": float(row.confidence),
                "source": str(row.source),
                "source_url": str(row.source_url) if row.source_url is not None else None,
                "source_hash": str(row.source_hash),
            }
        )

    grouped: dict[str, dict[str, object]] = {}
    for row in securities:
        cik = str(row.cik)
        group = grouped.setdefault(
            cik,
            {
                "cik": cik,
                "company_id": int(row.company_id),
                "company_name": str(row.name),
                "blocking_membership_ids": sorted(
                    int(blocker.id) for blocker in blocker_rows if str(blocker.cik) == cik
                ),
                "securities": [],
            },
        )
        security_id = int(row.id)
        security_payload = {
            "security_id": security_id,
            "security_type": str(row.security_type),
            "share_class": str(row.share_class) if row.share_class is not None else None,
            "identities": identities_by_security.get(security_id, []),
            "memberships": memberships_by_security.get(security_id, []),
        }
        securities_payload = group["securities"]
        if not isinstance(securities_payload, list):
            raise RuntimeError("internal topology grouping error")
        securities_payload.append(security_payload)

    issuers = [grouped[cik] for cik in sorted(grouped)]
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "universe_code": normalized,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "blocking_membership_count": len(blocker_ids),
        "issuer_count": len(issuers),
        "issuers": issuers,
    }
    payload["topology_id"] = _digest(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit HU-5 blocker security topology.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--universe-code", default="sp500")
    parser.add_argument("--window-start", type=_date, default=date(2010, 1, 1))
    parser.add_argument("--window-end", type=_date, default=date(2026, 9, 1))
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            payload = build_report(
                session,
                universe_code=args.universe_code,
                window_start=args.window_start,
                window_end=args.window_end,
            )
            session.rollback()
    finally:
        engine.dispose()

    payload["interpretation"] = (
        "Read-only topology for issuers touched by provisional memberships. Sibling securities "
        "must not be merged merely because they share a CIK; this artifact exposes identity and "
        "membership adjacency so a separate reviewed planner can distinguish ticker transitions "
        "from simultaneous share classes."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"topology_id": payload["topology_id"], "blocking_membership_count": payload["blocking_membership_count"], "issuer_count": payload["issuer_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
