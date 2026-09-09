from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from apps.api.app.services.company_reference_cache import CompanyReferenceCache
from fdre.retrieval.preprocess import CompanyReference


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_company_reference_cache_refreshes_after_ttl() -> None:
    clock = MutableClock()
    calls = 0

    def loader(session: Session) -> list[CompanyReference]:
        nonlocal calls
        del session
        calls += 1
        return [CompanyReference(ticker=f"T{calls}", name=f"Company {calls}")]

    cache = CompanyReferenceCache(
        ttl_seconds=10,
        stale_if_error_seconds=30,
        loader=loader,
        clock=clock,
    )
    session = Session()

    first = cache.get(session)
    clock.value = 5
    second = cache.get(session)
    clock.value = 11
    third = cache.get(session)

    assert [item.ticker for item in first] == ["T1"]
    assert second == first
    assert [item.ticker for item in third] == ["T2"]
    assert calls == 2


def test_company_reference_cache_serves_bounded_stale_snapshot_on_refresh_error() -> None:
    clock = MutableClock()
    fail = False

    def loader(session: Session) -> list[CompanyReference]:
        if fail:
            session.execute(text("SELECT 1"))
            raise RuntimeError("database unavailable")
        return [CompanyReference(ticker="AAPL", name="Apple Inc.")]

    cache = CompanyReferenceCache(
        ttl_seconds=10,
        stale_if_error_seconds=20,
        loader=loader,
        clock=clock,
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    session = Session(engine)
    initial = cache.get(session)
    fail = True

    clock.value = 15
    assert cache.get(session) == initial
    assert session.in_transaction() is False

    clock.value = 31
    with pytest.raises(RuntimeError, match="database unavailable"):
        cache.get(session)
    session.rollback()
    session.close()
    engine.dispose()


def test_company_reference_cache_serializes_concurrent_refreshes() -> None:
    clock = MutableClock()
    calls = 0
    calls_lock = Lock()
    refresh_started = Event()
    release_refresh = Event()
    slow_refresh = False

    def loader(session: Session) -> list[CompanyReference]:
        nonlocal calls
        del session
        with calls_lock:
            calls += 1
            call_number = calls
        if slow_refresh:
            refresh_started.set()
            assert release_refresh.wait(timeout=2)
        return [CompanyReference(ticker=f"T{call_number}", name="Company")]

    cache = CompanyReferenceCache(
        ttl_seconds=10,
        stale_if_error_seconds=0,
        loader=loader,
        clock=clock,
    )
    session = Session()
    cache.get(session)
    clock.value = 11
    slow_refresh = True

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get, session)
        assert refresh_started.wait(timeout=1)
        second = executor.submit(cache.get, session)
        release_refresh.set()
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)

    assert first_result == second_result
    assert calls == 2
