from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

INGESTION_LOCK_NAMESPACE = 0x46445245  # FDRE
INGESTION_LOCK_ID = 0x494E4754  # INGT


def lane_lock_id(lane: int) -> int:
    """Advisory-lock id for a parallel ingestion lane.

    Lane 0 keeps the historical global lock id so single-lane runs are
    unchanged. Disjoint lanes (>0) get distinct ids so they ingest concurrently
    while a lane's own batches still serialize against each other.
    """
    if lane < 0:
        raise ValueError("lane must be non-negative")
    return INGESTION_LOCK_ID + lane


@contextmanager
def serialized_ingestion(
    engine: Engine, *, skip_if_locked: bool, lock_id: int = INGESTION_LOCK_ID
) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        yield True
        return

    params = {
        "namespace": INGESTION_LOCK_NAMESPACE,
        "lock_id": lock_id,
    }
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if skip_if_locked:
            acquired = bool(
                connection.scalar(
                    text("SELECT pg_try_advisory_lock(:namespace, :lock_id)"),
                    params,
                )
            )
            if not acquired:
                print({"status": "skipped_ingestion_lock_busy"}, flush=True)
                yield False
                return
        else:
            print({"status": "waiting_for_ingestion_lock"}, flush=True)
            connection.execute(
                text("SELECT pg_advisory_lock(:namespace, :lock_id)"),
                params,
            )
        print({"status": "acquired_ingestion_lock"}, flush=True)
        try:
            yield True
        finally:
            try:
                released = connection.scalar(
                    text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
                    params,
                )
                print(
                    {
                        "status": "released_ingestion_lock",
                        "released": bool(released),
                    },
                    flush=True,
                )
            except SQLAlchemyError as error:
                print(
                    {
                        "status": "release_ingestion_lock_failed",
                        "error": type(error).__name__,
                        "message": str(error)[-1000:],
                    },
                    flush=True,
                )


def ingestion_lock_is_busy(engine: Engine) -> bool:
    if engine.dialect.name != "postgresql":
        return False

    params = {
        "namespace": INGESTION_LOCK_NAMESPACE,
        "lock_id": INGESTION_LOCK_ID,
    }
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.scalar(
                text("SELECT pg_try_advisory_lock(:namespace, :lock_id)"),
                params,
            )
        )
        if not acquired:
            return True
        released = connection.scalar(
            text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
            params,
        )
        if not released:
            raise RuntimeError("Failed to release ingestion advisory lock probe")
    return False
