from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic

from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from fdre.retrieval.preprocess import CompanyReference, load_company_references

CompanyReferenceLoader = Callable[[Session], list[CompanyReference]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class CompanyReferenceSnapshot:
    references: tuple[CompanyReference, ...]
    loaded_at: float


class CompanyReferenceCache:
    """TTL snapshot with serialized refresh and bounded stale-if-error fallback."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        stale_if_error_seconds: int,
        loader: CompanyReferenceLoader = load_company_references,
        clock: Clock = monotonic,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        if stale_if_error_seconds < 0:
            raise ValueError("stale_if_error_seconds must be non-negative")
        self._ttl_seconds = float(ttl_seconds)
        self._stale_if_error_seconds = float(stale_if_error_seconds)
        self._loader = loader
        self._clock = clock
        self._snapshot: CompanyReferenceSnapshot | None = None
        self._refresh_lock = Lock()

    def get(self, session: Session) -> tuple[CompanyReference, ...]:
        now = self._clock()
        snapshot = self._snapshot
        if snapshot is not None and self._is_fresh(snapshot, now):
            return snapshot.references

        with self._refresh_lock:
            now = self._clock()
            snapshot = self._snapshot
            if snapshot is not None and self._is_fresh(snapshot, now):
                return snapshot.references
            try:
                references = tuple(self._loader(session))
            except Exception:
                if snapshot is not None and self._can_serve_stale(snapshot, now):
                    if session.in_transaction():
                        session.rollback()
                    return snapshot.references
                raise
            self._snapshot = CompanyReferenceSnapshot(
                references=references,
                loaded_at=now,
            )
            return references

    def invalidate(self) -> None:
        with self._refresh_lock:
            self._snapshot = None

    def _is_fresh(
        self,
        snapshot: CompanyReferenceSnapshot,
        now: float,
    ) -> bool:
        return now - snapshot.loaded_at <= self._ttl_seconds

    def _can_serve_stale(
        self,
        snapshot: CompanyReferenceSnapshot,
        now: float,
    ) -> bool:
        maximum_age = self._ttl_seconds + self._stale_if_error_seconds
        return now - snapshot.loaded_at <= maximum_age


@lru_cache(maxsize=16)
def _company_reference_cache(
    ttl_seconds: int,
    stale_if_error_seconds: int,
) -> CompanyReferenceCache:
    return CompanyReferenceCache(
        ttl_seconds=ttl_seconds,
        stale_if_error_seconds=stale_if_error_seconds,
    )


def company_references_for_request(
    session: Session,
    settings: Settings,
) -> tuple[CompanyReference, ...]:
    return _company_reference_cache(
        settings.company_reference_cache_ttl_seconds,
        settings.company_reference_cache_stale_if_error_seconds,
    ).get(session)


def invalidate_company_reference_cache() -> None:
    """Drop process-local snapshots so the next request reloads authoritative rows."""

    _company_reference_cache.cache_clear()
