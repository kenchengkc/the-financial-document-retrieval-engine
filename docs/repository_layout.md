# Repository layout

FDRE uses an application + Python `src` layout.

```text
apps/
  api/        FastAPI, SQLAlchemy persistence, provider/config adapters
  web/        Next.js user interface
src/fdre/     Shared Python engine: ingestion, parsing, retrieval, research, evals
tests/fdre/   Tests for the shared Python engine
scripts/      Operator, ingestion, benchmark, and research entrypoints
data/         Version-controlled benchmark and seed artifacts
docs/         Architecture, methodology, benchmark, and research documentation
```

`src/fdre` is the shared engine used by the API, scripts, CI, and research workflows. The filesystem
move does not change the public Python namespace: callers continue to import `fdre.*`.

The shared engine is not currently persistence-independent: several modules use the API SQLAlchemy
models and settings directly. That dependency is intentional and explicit until a measured need
justifies extracting a separate storage adapter layer. Do not create additional packages merely to
make the repository look more modular.

The bounded LangGraph answer workflow remains in `src/fdre/graph` because the production answer
service actively executes it.
