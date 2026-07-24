from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from apps.api.app.models import ResearchMetricSnapshot


def read_metric_snapshot(session: Session, metric_key: str) -> dict[str, Any] | None:
    snapshot = session.get(ResearchMetricSnapshot, metric_key)
    return dict(snapshot.payload_json) if snapshot is not None else None


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
