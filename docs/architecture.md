# Architecture

FDRE is being implemented in phases. Phases 1 and 2 establish the API, Docker foundation, database model, and migration baseline. Phases 3 through 5 add cached SEC metadata ingestion, deterministic filing downloads, and layout-aware HTML parsing into database-backed document elements.

Later phases will add chunking, indexing, hybrid retrieval, reranking, citation verification, abstention, LangGraph orchestration, structured financial facts, observability, and the frontend evidence viewer.

## Ingestion Boundary

- `SECClient` owns user-agent enforcement, local HTTP caching, and request pacing.
- Filing metadata is upserted idempotently before raw content is downloaded.
- Filing HTML uses a stable CIK/accession path and SHA-256 content identity.
- The HTML parser emits ordered typed elements and preserves tables as Markdown.
- Downloaded files and cached responses remain outside version control.

## Cost Model

The MVP architecture should stay local-first and cheap:

- PostgreSQL is the primary database, sparse retrieval engine, metadata store, trace store, and financial facts store.
- `pgvector` is optional. The system must have a local deterministic embedding fallback.
- OpenSearch, external embedding APIs, hosted rerankers, and LLM generation are optional extensions behind provider interfaces.
- SEC requests should use local caching and rate limiting.
- Tests must be offline and must not require paid providers.
- Extra services such as queues, distributed workers, and search clusters should be added only after a concrete bottleneck appears.

The strongest portfolio signal should come from retrieval engineering: parsing quality, chunk metadata, hybrid ranking, eval methodology, citation verification, abstention policy, and auditable traces.
