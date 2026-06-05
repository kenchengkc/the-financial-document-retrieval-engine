# AGENTS.md

## Project

FDRE, the Financial Document Retrieval Engine, is a layout-aware search and retrieval engine for financial documents.

It ingests SEC filings, parses structured document elements, indexes text and tables, retrieves evidence with hybrid search, verifies citations, and supports answer abstention when evidence is insufficient.

This is a financial data systems and AI retrieval project, not a generic chatbot.

## Core Principles

- Retrieval quality is the main product.
- Every factual generated answer must be grounded in cited evidence.
- The system should abstain when evidence is weak.
- Prefer deterministic preprocessing and validation before LLM-based decisions.
- Keep LangGraph workflows bounded and inspectable.
- Keep modules small, typed, and testable.
- No secrets in code.
- No paid APIs required for MVP.
- No live network calls in unit tests.
- Do not commit raw filings, caches, embeddings, indexes, or database dumps.

## Cost-Effective Architecture

- Prefer local-first, low-infrastructure choices for the MVP.
- Use PostgreSQL for relational data, metadata filtering, retrieval traces, financial facts, and full-text search before adding another search service.
- Use `pgvector` only when available; keep a deterministic local embedding fallback.
- Keep OpenSearch, paid embedding APIs, hosted rerankers, and paid LLM generation optional and behind provider interfaces.
- Make every core workflow runnable without paid APIs.
- Favor batch/offline ingestion, caching, and eval artifacts over repeated live calls.
- Do not add distributed systems, queues, background workers, or extra services until there is a demonstrated need.
- Optimize for a strong portfolio signal per dollar: parsing quality, metadata design, hybrid ranking, evals, citations, abstention, and traceability matter more than expensive providers.

## Stack

- Python 3.11+
- FastAPI
- PostgreSQL
- SQLAlchemy 2.0
- Alembic
- Pydantic v2
- PostgreSQL full-text search
- Optional pgvector
- LangGraph
- pytest
- ruff
- mypy
- Next.js
- Docker Compose

## Repository Structure

- `apps/api/` contains the FastAPI service, routes, schemas, services, and API tests.
- `apps/web/` is reserved for the Next.js evidence inspection frontend.
- `packages/fdre/` contains the reusable `fdre` Python package.
- `scripts/` contains operational scripts for ingestion, parsing, indexing, and evals.
- `data/sample/` contains tiny committed fixtures.
- `data/raw/`, `data/cache/`, and `data/processed/` contain ignored generated or downloaded data.
- `docs/` contains architecture, data model, eval, demo, and resume documentation.

## Coding Conventions

- Use Python 3.11+ syntax and type hints.
- Prefer Pydantic v2 models for API and workflow state.
- Keep modules small and focused.
- Prefer deterministic logic before LLM calls.
- Use SQLAlchemy 2.0 style APIs.
- Keep API schemas separate from database models.
- Avoid arbitrary LLM-generated SQL in the MVP.
- Avoid open-ended recursive agent loops.

## Definition of Done

A task is done only when:

- Code is implemented.
- Tests are added or updated.
- Existing tests pass locally.
- Linting passes locally.
- Types pass locally where practical.
- CI-relevant checks are considered before delivery.
- README or docs are updated if behavior changed.
- No secrets or generated data are committed.
- The implementation is small enough to review.

## Commands

Backend:

```bash
pytest
ruff check .
mypy .
```

API:

```bash
uvicorn apps.api.app.main:app --reload
```

Docker:

```bash
docker compose up --build
```

Frontend:

```bash
cd apps/web
npm run lint
npm run typecheck
npm run build
```

## Verification Policy

- Run relevant tests after every code change.
- For backend changes, run `pytest`, `ruff check .`, and `mypy .`.
- For frontend changes, run `npm run lint`, `npm run typecheck`, and `npm run build` from `apps/web`.
- For Docker or deployment changes, run `docker compose config` and, when Docker is available, `docker compose up --build`.
- After starting a frontend or deployed web target, use Playwright or agent-browser for visual checks of the key user flow.
- Do not claim a check passed unless it was actually run in the current environment.

## CI/CD Policy

- Keep CI fast, deterministic, and low-cost.
- CI should run install, lint, type checks, tests, and lightweight configuration validation.
- Do not add deployment automation until the target environment and secrets policy are explicit.
- Do not put secrets in workflow files.
- Prefer mocked providers in CI; do not require paid APIs or live SEC calls.

## Data Policy

Do not commit:

- raw SEC filings
- downloaded PDFs
- caches
- embeddings
- vector indexes
- database dumps
- `.env` files
- API keys

Use:

- `data/sample/` for tiny fixtures
- `data/raw/` for ignored downloaded files
- `data/cache/` for ignored HTTP cache
- `data/processed/` for ignored generated artifacts

## Testing Policy

- Unit tests must not hit live APIs.
- SEC API tests must use mocked HTTP responses.
- Embedding tests must use fake deterministic embeddings.
- Reranker tests must use fake deterministic rerankers.
- LLM generation tests must use mock generators.

## Agent Workflow Policy

- Do not create open-ended recursive agent loops.
- Every LangGraph node must be small and testable.
- Graph state must be serializable.
- Every answer run should have traceable state transitions.
- Retrieval failures should route to abstention, not hallucination.

## Security And Secrets Policy

- Never commit secrets, API keys, access tokens, cookies, or private credentials.
- Keep local secrets in `.env`, which is ignored.
- Keep public configuration examples in `.env.example`.
- Validate external inputs at API boundaries.

## Environment Policy

- `.env.example` is the source of truth for documented configuration.
- `.env` is for local developer values and must stay untracked.
- Optional paid providers should be unset by default.
- Tests should use deterministic local or mock providers.
- New environment variables must be added to `.env.example` with a safe default or an empty placeholder.

## PR Expectations

- Keep changes scoped to the phase or task.
- Include tests for new behavior.
- Explain user-facing or architectural changes in the README or docs.
- Document known limitations when a phase intentionally leaves behavior incomplete.
- Avoid large cross-phase changes unless explicitly requested.

## Restrictions On Large Changes

- Do not implement later phases while working on an earlier phase.
- Do not introduce new frameworks or providers without a clear project need.
- Do not commit generated artifacts or downloaded financial data.
- Prefer reviewable increments over broad rewrites.

## Restrictions On Live Network Calls In Tests

- Unit tests must be offline.
- Mock SEC, embedding, reranker, and LLM providers.
- Use local fixtures for filings and company facts.
- Integration tests that require network access must be explicitly marked and excluded from default test runs.
