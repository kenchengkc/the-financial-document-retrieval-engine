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
- `packages/fdre/`: reusable ingestion, parsing, retrieval, graph, evaluation, and research code.
- `scripts/retrieval_pipeline.py`: primary artifact/research CLI.
- `scripts/ingest_ticker_batch.py`: resumable operational ingestion.
- `data/sample/`: small deterministic fixtures only.
- `docs/`: architecture, roadmap, and benchmark report.

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
