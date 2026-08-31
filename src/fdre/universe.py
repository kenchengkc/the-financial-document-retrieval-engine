"""Public point-in-time universe query and export API for Historical Universe HU-3."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_universe import (
    SecurityIdentityRecord,
    UniverseMembershipRecord,
    UniverseSnapshot,
    VerificationStatus,
    build_universe_snapshot,
)

UniverseExportFormat = Literal["json", "parquet"]


def _parse_as_of(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("as_of must use YYYY-MM-DD") from exc


def _verification_status(value: str) -> VerificationStatus:
    if value not in {"verified", "provisional", "rejected"}:
        raise ValueError(f"unsupported historical-universe verification status: {value}")
    return cast(VerificationStatus, value)


def _load_memberships(
    session: Session,
    *,
    universe_code: str,
    as_of: date,
) -> tuple[UniverseMembershipRecord, ...]:
    rows = session.execute(
        select(
            UniverseMembership.universe_code,
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.source_hash,
            UniverseMembership.verification_status,
            UniverseMembership.confidence,
        )
        .where(
            UniverseMembership.universe_code == universe_code,
            UniverseMembership.effective_from <= as_of,
            (UniverseMembership.effective_to.is_(None) | (as_of < UniverseMembership.effective_to)),
            UniverseMembership.verification_status != "rejected",
        )
        .order_by(
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.id,
        )
    ).all()
    return tuple(
        UniverseMembershipRecord(
            universe_code=str(row.universe_code),
            security_id=int(row.security_id),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=_verification_status(str(row.verification_status)),
            confidence=float(row.confidence),
        )
        for row in rows
    )


def _load_identities(
    session: Session,
    *,
    security_ids: tuple[int, ...],
    as_of: date,
) -> tuple[SecurityIdentityRecord, ...]:
    if not security_ids:
        return ()
    rows = session.execute(
        select(
            SecurityIdentityPeriod.security_id,
            Company.cik,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.name,
            SecurityIdentityPeriod.exchange,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.source_hash,
            SecurityIdentityPeriod.verification_status,
            SecurityIdentityPeriod.confidence,
        )
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            SecurityIdentityPeriod.security_id.in_(security_ids),
            SecurityIdentityPeriod.effective_from <= as_of,
            (
                SecurityIdentityPeriod.effective_to.is_(None)
                | (as_of < SecurityIdentityPeriod.effective_to)
            ),
            SecurityIdentityPeriod.verification_status != "rejected",
        )
        .order_by(
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.id,
        )
    ).all()
    return tuple(
        SecurityIdentityRecord(
            security_id=int(row.security_id),
            cik=str(row.cik),
            symbol=str(row.symbol),
            name=str(row.name) if row.name is not None else None,
            exchange=str(row.exchange) if row.exchange is not None else None,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=_verification_status(str(row.verification_status)),
            confidence=float(row.confidence),
        )
        for row in rows
    )


def universe_from_session(
    session: Session,
    universe_code: str,
    *,
    as_of: date | str,
    include_provisional: bool = False,
) -> UniverseSnapshot:
    """Return one fail-closed historical universe snapshot from a database session."""

    normalized_universe = universe_code.strip().lower()
    if not normalized_universe:
        raise ValueError("universe_code is required")
    parsed_as_of = _parse_as_of(as_of)
    memberships = _load_memberships(
        session,
        universe_code=normalized_universe,
        as_of=parsed_as_of,
    )
    security_ids = tuple(sorted({row.security_id for row in memberships}))
    identities = _load_identities(session, security_ids=security_ids, as_of=parsed_as_of)
    return build_universe_snapshot(
        universe_code=normalized_universe,
        as_of=parsed_as_of,
        memberships=memberships,
        identities=identities,
        include_provisional=include_provisional,
    )


def universe(
    universe_code: str,
    *,
    as_of: date | str,
    include_provisional: bool = False,
    database_url: str | None = None,
) -> UniverseSnapshot:
    """Public ``fdre.universe(...)`` entry point.

    The default database URL follows the same FDRE application configuration as the API. Passing
    ``database_url`` makes research scripts and exact replay explicit and self-contained.
    """

    engine = create_db_engine(database_url)
    try:
        with Session(engine) as session:
            return universe_from_session(
                session,
                universe_code,
                as_of=as_of,
                include_provisional=include_provisional,
            )
    finally:
        engine.dispose()


def snapshot_to_dict(snapshot: UniverseSnapshot) -> dict[str, object]:
    """Serialize a snapshot without dropping its PIT provenance hashes."""

    return {
        "schema_version": "fdre-hu3-universe-snapshot-v1",
        "snapshot_id": snapshot.snapshot_id,
        "universe_code": snapshot.universe_code,
        "as_of": snapshot.as_of.isoformat(),
        "includes_provisional": snapshot.includes_provisional,
        "constituent_count": len(snapshot.constituents),
        "constituents": [
            {
                "security_id": row.security_id,
                "cik": row.cik,
                "symbol": row.symbol,
                "name": row.name,
                "exchange": row.exchange,
                "membership_effective_from": row.membership_effective_from.isoformat(),
                "identity_effective_from": row.identity_effective_from.isoformat(),
                "membership_source_hash": row.membership_source_hash,
                "identity_source_hash": row.identity_source_hash,
                "verification_status": row.verification_status,
            }
            for row in snapshot.constituents
        ],
    }


def _parquet_rows(snapshot: UniverseSnapshot) -> list[dict[str, object]]:
    payload = snapshot_to_dict(snapshot)
    constituents = payload["constituents"]
    if not isinstance(constituents, list):
        raise TypeError("serialized constituents must be a list")
    rows: list[dict[str, object]] = []
    for raw_row in constituents:
        if not isinstance(raw_row, Mapping):
            raise TypeError("serialized constituent must be a mapping")
        rows.append(
            {
                "snapshot_id": snapshot.snapshot_id,
                "universe_code": snapshot.universe_code,
                "as_of": snapshot.as_of.isoformat(),
                "includes_provisional": snapshot.includes_provisional,
                **dict(raw_row),
            }
        )
    return rows


def write_universe_snapshot(
    snapshot: UniverseSnapshot,
    path: Path | str,
    *,
    export_format: UniverseExportFormat | None = None,
) -> Path:
    """Export one replayable universe snapshot as JSON or Parquet."""

    output = Path(path)
    resolved_format = export_format or (
        "parquet" if output.suffix.lower() == ".parquet" else "json"
    )
    if resolved_format not in {"json", "parquet"}:
        raise ValueError(f"unsupported universe export format: {resolved_format}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if resolved_format == "json":
        output.write_text(
            json.dumps(snapshot_to_dict(snapshot), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - exercised only without [data]
        raise RuntimeError("Parquet export requires the fdre[data] optional dependencies") from exc
    rows = _parquet_rows(snapshot)
    schema = pa.schema(
        [
            ("snapshot_id", pa.string()),
            ("universe_code", pa.string()),
            ("as_of", pa.string()),
            ("includes_provisional", pa.bool_()),
            ("security_id", pa.int64()),
            ("cik", pa.string()),
            ("symbol", pa.string()),
            ("name", pa.string()),
            ("exchange", pa.string()),
            ("membership_effective_from", pa.string()),
            ("identity_effective_from", pa.string()),
            ("membership_source_hash", pa.string()),
            ("identity_source_hash", pa.string()),
            ("verification_status", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    metadata = dict(table.schema.metadata or {})
    metadata[b"fdre_snapshot_id"] = snapshot.snapshot_id.encode("utf-8")
    metadata[b"fdre_universe_code"] = snapshot.universe_code.encode("utf-8")
    metadata[b"fdre_as_of"] = snapshot.as_of.isoformat().encode("utf-8")
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, output)
    return output
