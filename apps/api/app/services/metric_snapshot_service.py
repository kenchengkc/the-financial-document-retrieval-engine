from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.models import ResearchMetricSnapshot


def read_metric_snapshot(session: Session, metric_key: str) -> dict[str, Any] | None:
    snapshot = session.get(ResearchMetricSnapshot, metric_key)
    return dict(snapshot.payload_json) if snapshot is not None else None


def read_fresh_metric_snapshot(
    session: Session,
    metric_key: str,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if ttl_seconds <= 0:
        return None
    snapshot = session.get(ResearchMetricSnapshot, metric_key)
    if snapshot is None:
        return None
    refreshed_at = snapshot.refreshed_at
    if refreshed_at.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) - refreshed_at > timedelta(seconds=ttl_seconds):
        return None
    return dict(snapshot.payload_json)


def write_metric_snapshot(
    session: Session,
    *,
    metric_key: str,
    payload: dict[str, Any],
) -> None:
    snapshot = session.get(ResearchMetricSnapshot, metric_key)
    if snapshot is None:
        session.add(
            ResearchMetricSnapshot(
                metric_key=metric_key,
                payload_json=payload,
                refreshed_at=datetime.now(UTC),
            )
        )
        return
    snapshot.payload_json = payload
    snapshot.refreshed_at = datetime.now(UTC)


def prune_metric_snapshots(
    session: Session,
    *,
    prefix: str,
    keep: int,
) -> None:
    keys = list(
        session.scalars(
            select(ResearchMetricSnapshot.metric_key)
            .where(ResearchMetricSnapshot.metric_key.startswith(prefix))
            .order_by(ResearchMetricSnapshot.refreshed_at.desc())
            .offset(keep)
        )
    )
    if keys:
        session.execute(
            delete(ResearchMetricSnapshot).where(
                ResearchMetricSnapshot.metric_key.in_(keys)
            )
        )


def delete_metric_snapshots(session: Session, *, prefixes: tuple[str, ...]) -> None:
    for prefix in prefixes:
        session.execute(
            delete(ResearchMetricSnapshot).where(
                ResearchMetricSnapshot.metric_key.startswith(prefix)
            )
        )
