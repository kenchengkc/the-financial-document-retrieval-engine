# FDRE Engineering Rules

FDRE is financial research infrastructure, not a generic chatbot or trading system.

## Priorities

- Retrieval quality, point-in-time correctness, citations, and reproducibility are product
  requirements.
- Prefer deterministic processing and bounded LangGraph nodes.
- Keep PostgreSQL as the metadata, full-text, vector, fact, trace, and experiment store until
  measured requirements justify another service.
- Keep paid embeddings, rerankers, and generation behind provider interfaces.
- Do not add live trading, portfolio optimization, arbitrary generated SQL, distributed queues, or
  open-ended agent loops.

## Structure

- `apps/api/`: FastAPI routes, schemas, services, models, migrations, and API tests.
- `apps/web/`: Next.js research interface and Playwright tests.
- `src/fdre/`: reusable ingestion, parsing, retrieval, graph, evaluation, universe, and research code.
- `scripts/benchmarks/`: retrieval and cross-sectional benchmark tooling.
- `scripts/ingestion/`: operational SEC ingestion, repair, and catalog utilities.
- `scripts/pipelines/`: top-level orchestration entry points.
- `scripts/research/`: reproducible research and experiment entry points.
- `scripts/research/historical_universe/`: Historical Universe audits, materialization, and gates.
- `tests/unit/fdre/`: reusable-library unit tests; application tests remain colocated under `apps/`.
- `data/sample/`: small deterministic fixtures only.
- `docs/architecture/`: system and lineage architecture.
- `docs/evaluations/`: evaluation plans and benchmark results.
- `docs/research/`: research-system specifications and archive documentation.

Canonical operational entry points include:

- `python -m scripts.pipelines.retrieval_pipeline`
- `python -m scripts.ingestion.ingest_ticker_batch`
- `python -m scripts.research.historical_universe.universe_snapshot`

## Code

- Python 3.11+, typed SQLAlchemy 2.0, Pydantic v2, small testable modules.
- No network calls in unit tests; mock SEC and paid providers.
- Every factual answer must cite retrieved evidence or abstain.
- Every temporal export must reject future information.
- Add environment variables to `.env.example` with safe defaults or empty values.
- Do not commit secrets, filings, caches, embeddings, market data, generated outputs, or dumps.

## Done

Run the relevant checks before committing:

```bash
pytest
ruff check .
mypy .
alembic check
docker compose config

cd apps/web
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

Use Playwright or agent-browser after frontend changes. Keep commits scoped and preserve unrelated
worktree changes.
