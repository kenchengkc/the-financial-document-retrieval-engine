# Codex Plan

Implement FDRE in small reviewable phases.

Completed scope:

1. Phase 0: create durable project instructions in `AGENTS.md`.
2. Phase 1: create the repository foundation, FastAPI health endpoint, Docker Compose stack, and quality tooling.
3. Phase 2: add SQLAlchemy models, indexes, Alembic migrations, and offline migration tests.
4. Phase 3: add cached, rate-limited SEC submissions ingestion and metadata upserts.
5. Phase 4: add deterministic filing downloads, hashes, duplicate skipping, and database paths.
6. Phase 5: add layout-aware SEC HTML parsing and document element persistence.

Next scope:

1. Phase 6: add element-aware text and table chunking.
