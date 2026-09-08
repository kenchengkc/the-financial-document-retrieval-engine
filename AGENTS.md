# FDRE Agent Guidance

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. It is the canonical engineering, research, verification, data, and cost contract for this repository.

Agent-specific rules:

- Preserve unrelated worktree changes and keep commits narrowly scoped.
- Do not weaken point-in-time, lineage, citation, benchmark, or fail-closed behavior to simplify a task.
- Do not add recurring infrastructure or paid model calls without satisfying the repository's $15/month operating-cost policy.
- Prefer reusable domain logic under `src/fdre/`; keep `scripts/` as thin operational entry points.
- No live trading, portfolio optimization, arbitrary generated SQL, distributed queues, or open-ended agent loops.
- Mock SEC and paid providers in unit tests; do not make live network calls from tests.
- Use Playwright or browser verification after frontend behavior changes.

Run the relevant verification commands from `CONTRIBUTING.md` before considering a change complete.
