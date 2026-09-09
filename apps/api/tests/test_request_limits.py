from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.services.request_limits import (
    BoundedCallerRateLimiter,
    ExpensiveRequestLimitMiddleware,
    InFlightRequestGate,
)


def _app_with_limits(
    *,
    requests_per_window: int = 1,
    max_in_flight: int = 2,
) -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    calls: list[str] = []
    app.add_middleware(
        ExpensiveRequestLimitMiddleware,
        requests_per_window=requests_per_window,
        window_seconds=60,
        max_callers=16,
        max_in_flight=max_in_flight,
        overload_retry_after_seconds=2,
    )

    @app.post("/search")
    def search() -> dict[str, bool]:
        calls.append("provider-work")
        return {"ok": True}

    return app, calls


def test_rate_limit_rejects_before_handler_and_ignores_forwarded_identity() -> None:
    app, calls = _app_with_limits()
    with TestClient(app) as client:
        first = client.post("/search", headers={"X-Forwarded-For": "198.51.100.10"})
        second = client.post("/search", headers={"X-Forwarded-For": "203.0.113.20"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert calls == ["provider-work"]


def test_rate_limiter_bounds_caller_state() -> None:
    limiter = BoundedCallerRateLimiter(
        requests_per_window=5,
        window_seconds=60,
        max_callers=2,
    )

    assert limiter.check("caller-a", now=1).allowed
    assert limiter.check("caller-b", now=2).allowed
    assert limiter.check("caller-c", now=3).allowed

    assert limiter.caller_count == 2


def test_in_flight_gate_is_non_blocking_and_bounded() -> None:
    gate = InFlightRequestGate(2)

    assert gate.try_acquire() is True
    assert gate.try_acquire() is True
    assert gate.try_acquire() is False
    assert gate.active == 2

    gate.release()
    assert gate.try_acquire() is True
    assert gate.active == 2


@pytest.mark.asyncio
async def test_concurrency_overload_rejects_before_second_handler_call() -> None:
    app = FastAPI()
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    app.add_middleware(
        ExpensiveRequestLimitMiddleware,
        requests_per_window=100,
        window_seconds=60,
        max_callers=16,
        max_in_flight=1,
        overload_retry_after_seconds=2,
    )

    @app.post("/answer")
    async def answer() -> dict[str, bool]:
        calls.append("provider-work")
        entered.set()
        await release.wait()
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first_task = asyncio.create_task(client.post("/answer"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        second = await client.post("/answer")
        release.set()
        first = await asyncio.wait_for(first_task, timeout=1)

    assert first.status_code == 200
    assert second.status_code == 503
    assert second.headers["Retry-After"] == "2"
    assert calls == ["provider-work"]
