# Architecture

FDRE is being implemented in phases. Phase 1 establishes the API, project configuration, Docker foundation, and test tooling. Phase 2 adds the SQLAlchemy data model and Alembic migration baseline.

Later phases will add SEC ingestion, parsing, chunking, indexing, hybrid retrieval, reranking, citation verification, abstention, LangGraph orchestration, structured financial facts, observability, and the frontend evidence viewer.

## Cost Model

The MVP architecture should stay local-first and cheap:

- PostgreSQL is the primary database, sparse retrieval engine, metadata store, trace store, and financial facts store.
- `pgvector` is optional. The system must have a local deterministic embedding fallback.
- OpenSearch, external embedding APIs, hosted rerankers, and LLM generation are optional extensions behind provider interfaces.
- SEC requests should use local caching and rate limiting.
- Tests must be offline and must not require paid providers.
- Extra services such as queues, distributed workers, and search clusters should be added only after a concrete bottleneck appears.

The strongest portfolio signal should come from retrieval engineering: parsing quality, chunk metadata, hybrid ranking, eval methodology, citation verification, abstention policy, and auditable traces.
