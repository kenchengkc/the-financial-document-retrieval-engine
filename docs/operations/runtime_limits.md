# API runtime limits

FDRE uses bounded in-process controls for interactive work before adding another recurring service.
These controls reduce accidental provider and database fan-out; they are **not** an account-wide
spending ledger or a distributed quota.

## Expensive-request guard

The API guards these routes before route code or provider work begins:

- `POST /answer`
- `POST /search`
- `POST /research/screen`
- `POST /research/thematic-scan`
- `GET /research/panel`
- `GET /research/panel/export`
- `GET /research/filing-differences/{accession_number}`

Each process applies a sliding-window request limit and a non-blocking in-flight concurrency
ceiling. Rate overflow returns `429 Too Many Requests`; concurrency overflow returns
`503 Service Unavailable`. Both include `Retry-After`.

Caller identity is the direct ASGI peer (`request.client.host`). FDRE does not trust arbitrary
`X-Forwarded-For` or similar request headers inside this limiter. When a deployment presents a
single trusted proxy as the peer, callers may share the same process-local bucket; changing that
requires an explicit trusted-proxy contract rather than accepting user-supplied forwarding data.

Limiter caller state is LRU-bounded by `API_EXPENSIVE_MAX_CALLERS`. All request and concurrency
limits are per process. Two workers can therefore admit roughly twice the configured work, and two
replicas roughly twice again. Provider-native quotas remain the authoritative upstream limits.

## Interactive PostgreSQL statement timeout

`DATABASE_STATEMENT_TIMEOUT_MS` is attached only to sessions created by the FastAPI request
dependency. SQLAlchemy applies it with PostgreSQL `SET LOCAL statement_timeout` whenever a request
transaction begins, including a new transaction after a route commits. PostgreSQL automatically
clears `SET LOCAL` on commit or rollback, so pooled connections do not retain the request timeout.
The dependency rolls back any still-open request transaction before returning the connection.

Operational scripts and intentionally long jobs that construct their own `Session(get_engine())`
do not carry the request-session marker and therefore do not inherit this interactive timeout.
Set the value to `0` only when an environment intentionally disables the request statement limit.

## Company-reference snapshot

Query preprocessing needs the current `(ticker, company name)` reference set for entity detection.
The authoritative rows remain in PostgreSQL, but the API holds a process-local snapshot so every
search does not scan the full `Company` table.

`COMPANY_REFERENCE_CACHE_TTL_SECONDS` controls normal refresh. Only one thread refreshes an expired
snapshot; concurrent requests reuse the result. If refresh fails, an existing snapshot can be
served only until its total age reaches `TTL + COMPANY_REFERENCE_CACHE_STALE_IF_ERROR_SECONDS`.
After that bound, refresh failure is surfaced instead of serving indefinitely stale references.
`invalidate_company_reference_cache()` provides an explicit process-local invalidation hook; in
multi-process deployments, normal TTL refresh remains the cross-process synchronization contract.

## Cost and measurement scope

This design adds no recurring infrastructure and no additional model call. It is expected to have
zero incremental monthly service cost. Configuration defaults are protection values, not latency or
availability SLOs. Any SLO claim must come from a declared workload measured in the target
deployment.
