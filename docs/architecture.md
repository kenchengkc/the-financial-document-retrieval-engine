# Architecture

FDRE uses a deliberately small production stack: FastAPI, Next.js, PostgreSQL, pgvector, Voyage
embeddings, and GitHub Actions. PostgreSQL owns retrieval, metadata, structured facts, traces,
operations, and research experiments.

## Boundaries

### SEC ingestion

- Cached, rate-limited SEC client with descriptive user-agent enforcement.
- Idempotent metadata upserts keyed by company and accession.
- SEC acceptance timestamp promoted to indexed `accepted_at` and `available_at` fields.
- Amendment status and original-accession lineage stored explicitly.
- SHA-256 file identity and deterministic CIK/accession storage paths.
- Form-specific depth controls support three annual and eight quarterly filings.

### Parsing and indexing

- HTML parser emits ordered text, section-header, title, and table elements.
- Text chunks never cross source-element boundaries.
- Tables retain Markdown and a compact summary representation.
- Embeddings are incremental and resumable.
- PostgreSQL uses a generated-maintained `tsvector` GIN index for lexical retrieval.
- Voyage 512-dimensional embeddings use a partial half-vector HNSW cosine index.
- Metadata indexes cover company, form, period, availability, section, and embedding model.

### Retrieval and answer workflow

- Exact ticker boundaries and unique normalized company aliases prevent substring inference.
- Broad thematic questions do not infer accidental ticker filters.
- Dense and sparse filters are applied in SQL before ranking.
- Hybrid retrieval uses reciprocal-rank fusion and optional reranking.
- The bounded LangGraph workflow routes text, table, and typed financial-fact retrieval.
- Evidence gates abstain for weak support, private information, unsupported forecasts, missing
  facts, or invalid citations.

### Research interfaces

- Filing differences use deterministic comparable periods and classify added, removed, and changed
  passages.
- Company Facts preserve raw facts and map restrained canonical metrics.
- Research panels include feature provenance, corpus snapshot, calculation version, and leakage
  validation.
- Event studies consume provider-neutral adjusted bars and persist configuration, dataset version,
  feature version, code SHA, statistics, and observations.
- Thematic scans cap evidence per issuer.

### Operations

- Every batch ingest creates a manifest with configuration, stage latency/status, before/after
  counts, provider usage, estimated cost, failures, and completion state.
- Quality audits report stale companies, missing forms, duplicate accessions, documents without
  chunks, chunks without embeddings, facts without documents, freshness, and coverage.
- GitHub Actions applies Alembic before production ingestion and runs daily incremental checks.
- Railway applies Alembic in `preDeployCommand`; the runtime command launches uvicorn only, so
  index construction does not consume the healthcheck window.

## Point-in-Time Model

`available_at` is the visibility boundary. Retrieval requires `document.available_at <= as_of`.
Panel generation requires every source document and XBRL fact to be available no later than the
row timestamp. Event features carry their maximum source timestamp and fail before analysis if it
exceeds event availability.

Amendments compare to their original accession. Non-amended 10-K filings compare with the prior
annual filing; 10-Q filings prefer the same quarter one year earlier.

## Cost Model

- One PostgreSQL service replaces separate vector, lexical, trace, fact, and experiment stores.
- SEC responses are cached.
- Embeddings are missing-only, batched, concurrent, rate-limited, and retryable.
- The default answer generator is deterministic and free.
- Market data is supplied as CSV or Parquet rather than coupled to a paid provider.
- OpenSearch, Kafka, distributed queues, portfolio simulation, and paid generation remain deferred.

## Known Constraints

- The reviewed 120-question holdout is published in `docs/eval_results.md`; Hybrid
  Recall@10 is 0.375 after automated paraphrase/regrounding (gate 0.85 needs humans).
- Single-name search p95 (~1.95 s) and cross-sectional p95 (~1.74 s) both meet gates.
- Exact-versus-ANN Recall@10 max delta is 0.00 with `hnsw.ef_search=400` on filtered searches.
- `FDXF` remains unindexed until an eligible 10-K/10-Q exists (verified Form 3/4/8-K only).
- 8-K ingestion remains gated on point-in-time benchmark results.
- PDF parsing is optional; the production corpus is SEC filing HTML.
