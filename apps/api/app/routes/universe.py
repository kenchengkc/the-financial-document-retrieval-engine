from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.db import get_db_session
from fdre.universe import snapshot_to_dict, universe_from_session
from fdre.universe_diff import compare_universe_snapshots, universe_diff_to_dict

router = APIRouter(prefix="/research/universe", tags=["research"])


@router.get("/{universe_code}")
def point_in_time_universe(
    universe_code: str,
    session: Annotated[Session, Depends(get_db_session)],
    as_of: Annotated[date, Query()],
    include_provisional: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    """Return a deterministic PIT universe snapshot with provenance hashes."""

    try:
        snapshot = universe_from_session(
            session,
            universe_code,
            as_of=as_of,
            include_provisional=include_provisional,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return snapshot_to_dict(snapshot)


@router.get("/{universe_code}/diff")
def point_in_time_universe_diff(
    universe_code: str,
    session: Annotated[Session, Depends(get_db_session)],
    from_as_of: Annotated[date, Query(alias="from")],
    to_as_of: Annotated[date, Query(alias="to")],
    include_provisional: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    """Compare two PIT snapshots by stable security identity and provenance."""

    try:
        before = universe_from_session(
            session,
            universe_code,
            as_of=from_as_of,
            include_provisional=include_provisional,
        )
        after = universe_from_session(
            session,
            universe_code,
            as_of=to_as_of,
            include_provisional=include_provisional,
        )
        return universe_diff_to_dict(compare_universe_snapshots(before, after))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
