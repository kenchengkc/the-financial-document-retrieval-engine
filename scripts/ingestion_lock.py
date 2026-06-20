from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

INGESTION_LOCK_NAMESPACE = 0x46445245  # FDRE
INGESTION_LOCK_ID = 0x494E4754  # INGT


@contextmanager
def serialized_ingestion(engine: Engine, *, skip_if_locked: bool) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        yield True
        return

    params = {
        "namespace": INGESTION_LOCK_NAMESPACE,
        "lock_id": INGESTION_LOCK_ID,
    }
    with engine.connect() as connection:
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


def ingestion_lock_is_busy(engine: Engine) -> bool:
    if engine.dialect.name != "postgresql":
        return False

    params = {
        "namespace": INGESTION_LOCK_NAMESPACE,
        "lock_id": INGESTION_LOCK_ID,
    }
    with engine.connect() as connection:
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
