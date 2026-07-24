from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.app.services.metric_snapshot_service import (
    delete_metric_snapshots,
    prune_metric_snapshots,
    read_fresh_metric_snapshot,
    write_metric_snapshot,
)

THEMATIC_CACHE_PREFIX = "thematic-v1:"
PANEL_CACHE_PREFIX = "panel-v2:"
RESEARCH_CACHE_PREFIXES = (THEMATIC_CACHE_PREFIX, PANEL_CACHE_PREFIX)
MAX_CACHE_ENTRIES_PER_KIND = 128

ModelT = TypeVar("ModelT", bound=BaseModel)


def research_cache_key(prefix: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()[:32]
    return f"{prefix}{digest}"


def read_cached_model(
    session: Session,
    *,
    cache_key: str,
    ttl_seconds: int,
    model_type: type[ModelT],
) -> ModelT | None:
    payload = read_fresh_metric_snapshot(
        session,
        cache_key,
        ttl_seconds=ttl_seconds,
    )
    return model_type.model_validate(payload) if payload is not None else None


def write_cached_model(
    session: Session,
    *,
    cache_key: str,
    prefix: str,
    value: BaseModel,
) -> None:
    write_metric_snapshot(
        session,
        metric_key=cache_key,
        payload=value.model_dump(mode="json"),
    )
    prune_metric_snapshots(
        session,
        prefix=prefix,
        keep=MAX_CACHE_ENTRIES_PER_KIND,
    )
    session.commit()


def invalidate_research_query_cache(session: Session) -> None:
    delete_metric_snapshots(session, prefixes=RESEARCH_CACHE_PREFIXES)
