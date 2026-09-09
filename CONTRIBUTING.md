# Contributing to FDRE

FDRE is point-in-time financial research infrastructure. Changes should improve correctness, reproducibility, retrieval quality, operational reliability, or maintainability without weakening the evidence and lineage contracts that make research results trustworthy.

## Engineering invariants

Treat these as product requirements rather than optional conventions:

- Filter research inputs by when information was actually available.
- Never infer historical universe membership from current constituents.
- Preserve source, filing, availability, and feature lineage through research outputs.
- Fail closed when issuer identity, security identity, evidence, or lineage is ambiguous.
- Every factual answer must cite retrieved evidence or abstain.
- Preserve immutable benchmark manifests and frozen first-run experiment artifacts.
- Report `REJECT` and `INSUFFICIENT` research outcomes directly; do not tune them away.
- Keep PostgreSQL/pgvector as the system of record until measurements justify another service.

## Repository boundaries

- `apps/api/` contains FastAPI routes, schemas, services, models, migrations, and API tests.
- `apps/web/` contains the Next.js research interface and Playwright coverage.
- `src/fdre/` contains reusable domain logic.
- `scripts/` contains operational and reproducible entry points; reusable business logic should migrate into `src/fdre/` rather than accumulate in scripts.
- `tests/unit/fdre/` contains reusable-library unit tests.
- `data/sample/` contains small deterministic fixtures only.
- `docs/architecture/` defines system and lineage contracts.
- `docs/evaluations/` defines evaluation methodology, benchmark visibility, and measured results.
- `docs/research/` defines research methodology and canonical research provenance.
- `docs/archive/` contains superseded or one-off investigation records.

## Change discipline

Keep pull requests small enough that correctness can be reviewed independently.

For changes that affect retrieval, research, or point-in-time behavior:

1. State the contract being changed.
2. Add or update tests before relying on new behavior.
3. Compare against the relevant development benchmark when ranking or retrieval semantics change.
4. Do not optimize against a published historical holdout and describe the result as unseen performance.
5. Preserve old frozen experiment identities; amended research uses a new versioned identity.

For production changes:

- Prefer bounded in-process reuse before adding infrastructure.
- Keep provider calls behind interfaces and mock all network access in unit tests.
- Add configuration to `.env.example` with safe defaults or empty values.
- Do not add a recurring service without a measured correctness, latency, scale, or cost requirement.
- Document any expected monthly cost change in the pull request.

The operating budget policy is defined in [`docs/operations/cost_budget.md`](docs/operations/cost_budget.md).

## Data policy

Do not commit secrets, `.env` files, SEC filing corpora, HTTP caches, embeddings, market-data caches, generated panels, database dumps, or other production datasets. Canonical benchmark manifests and explicitly frozen evaluation artifacts are exceptions when their presence is required for reproducibility.

## Python environment

Python dependencies are resolved in `uv.lock`. Use the frozen environment for development and CI rather than resolving directly from lower bounds in `pyproject.toml`:

```bash
python -m pip install uv==0.12.10
uv sync --frozen --extra dev --extra data
```

When dependency declarations intentionally change, regenerate `uv.lock` with the pinned resolver and review the lockfile diff in the same pull request.

## Verification

After syncing the environment, run the relevant checks:

```bash
uv run pytest
uv run ruff check .
uv run mypy .
uv run alembic check
docker compose config
```

For frontend changes:

```bash
cd apps/web
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

CI additionally validates PostgreSQL/pgvector migrations and retrieval indexes, the production Docker image, workflow configuration, and browser E2E paths.

## Scope

FDRE is research infrastructure. Do not add live trading, portfolio optimization, arbitrary generated SQL, distributed queues, autonomous/open-ended agent loops, or additional model calls solely for product appearance.
