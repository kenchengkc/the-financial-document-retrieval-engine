from __future__ import annotations

import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

_EXPENSIVE_EXACT_ROUTES = frozenset(
    {
        ("POST", "/answer"),
        ("POST", "/search"),
        ("GET", "/research/panel"),
        ("GET", "/research/panel/export"),
        ("POST", "/research/screen"),
        ("POST", "/research/thematic-scan"),
    }
)
_EXPENSIVE_PREFIX_ROUTES = (("GET", "/research/filing-differences/"),)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int | None = None


class BoundedCallerRateLimiter:
    """Process-local sliding-window limiter with bounded caller-state memory."""

    def __init__(
        self,
        *,
        requests_per_window: int,
        window_seconds: int,
        max_callers: int,
    ) -> None:
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        if max_callers < 1:
            raise ValueError("max_callers must be positive")
        self._requests_per_window = requests_per_window
        self._window_seconds = float(window_seconds)
        self._max_callers = max_callers
        self._requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, caller: str, *, now: float | None = None) -> RateLimitDecision:
        observed_at = monotonic() if now is None else now
        cutoff = observed_at - self._window_seconds
        with self._lock:
            requests = self._requests.get(caller)
            if requests is None:
                if len(self._requests) >= self._max_callers:
                    self._requests.popitem(last=False)
                requests = deque()
                self._requests[caller] = requests
            else:
                self._requests.move_to_end(caller)

            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self._requests_per_window:
                retry_after = max(
                    1,
                    math.ceil(requests[0] + self._window_seconds - observed_at),
                )
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after,
                )
            requests.append(observed_at)
            return RateLimitDecision(allowed=True)

    @property
    def caller_count(self) -> int:
        with self._lock:
            return len(self._requests)


class InFlightRequestGate:
    """Non-blocking process-local concurrency ceiling."""

    def __init__(self, max_in_flight: int) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be positive")
        self._max_in_flight = max_in_flight
        self._active = 0
        self._lock = Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self._max_in_flight:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._active < 1:
                raise RuntimeError("in-flight request gate released without an acquisition")
            self._active -= 1

    @property
    def active(self) -> int:
        with self._lock:
            return self._active


def is_expensive_request(method: str, path: str) -> bool:
    normalized_path = path.rstrip("/") or "/"
    normalized_method = method.upper()
    if (normalized_method, normalized_path) in _EXPENSIVE_EXACT_ROUTES:
        return True
    return any(
        normalized_method == route_method and normalized_path.startswith(prefix)
        for route_method, prefix in _EXPENSIVE_PREFIX_ROUTES
    )


def direct_caller_identity(request: Request) -> str:
    """Use only the ASGI peer identity; do not trust arbitrary forwarded headers."""

    return request.client.host if request.client is not None else "unknown"


class ExpensiveRequestLimitMiddleware(BaseHTTPMiddleware):
    """Reject excess expensive API work before route/provider execution begins."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_window: int,
        window_seconds: int,
        max_callers: int,
        max_in_flight: int,
        overload_retry_after_seconds: int,
    ) -> None:
        super().__init__(app)
        if overload_retry_after_seconds < 1:
            raise ValueError("overload_retry_after_seconds must be positive")
        self._rate_limiter = BoundedCallerRateLimiter(
            requests_per_window=requests_per_window,
            window_seconds=window_seconds,
            max_callers=max_callers,
        )
        self._in_flight = InFlightRequestGate(max_in_flight)
        self._overload_retry_after_seconds = overload_retry_after_seconds

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not is_expensive_request(request.method, request.url.path):
            return await call_next(request)

        decision = self._rate_limiter.check(direct_caller_identity(request))
        if not decision.allowed:
            retry_after = decision.retry_after_seconds or 1
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        "Too many expensive requests for this process. "
                        "Retry after the indicated interval."
                    )
                },
                headers={"Retry-After": str(retry_after)},
            )

        if not self._in_flight.try_acquire():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "This process is at its expensive-request concurrency limit. "
                        "Retry shortly."
                    )
                },
                headers={
                    "Retry-After": str(self._overload_retry_after_seconds),
                },
            )
        try:
            return await call_next(request)
        finally:
            self._in_flight.release()
