# Architecture

FDRE uses a deliberately small production stack: FastAPI, Next.js, PostgreSQL/pgvector, Voyage embeddings, and GitHub Actions. PostgreSQL remains the authoritative production data plane for retrieval, metadata, structured facts, point-in-time research state, traces, operations, and experiment manifests.

Current benchmark measurements live in [`eval_results.md`](eval_results.md). This document describes architecture and invariants rather than duplicating dated performance numbers.

## System boundaries

### SEC ingestion

- Cached, rate-limited SEC client with descriptive user-agent enforcement.
- Idempotent metadata upserts keyed by company and accession.
- SEC acceptance timestamps promoted to indexed `accepted_at` / `available_at` fields.
- Amendment status and original-accession lineage stored explicitly.
- SHA-256 source identity and deterministic CIK/accession storage paths.
- Bounded annual/quarterly depth controls for production ingestion.

### Parsing and indexing

- HTML parser emits ordered text, section-header, title, and table elements.
- Text chunks never cross source-element boundaries.
- Tables retain Markdown plus compact summaries.
- Embeddings are incremental and resumable.
- PostgreSQL uses generated `tsvector` GIN indexes for lexical retrieval.
- Voyage 512-dimensional embeddings use a partial `halfvec` HNSW cosine index.
- Metadata indexes cover company, form, period, availability, section, and embedding model.

### Retrieval and answer workflow

- Exact ticker boundaries and normalized company aliases avoid substring inference.
- Broad thematic questions do not infer accidental ticker filters.
- Dense/sparse filters are applied in SQL before ranking.
- Hybrid retrieval uses reciprocal-rank fusion with optional reranking.
- The bounded LangGraph workflow routes text, table, and typed-financial-fact retrieval.
- Evidence gates abstain for weak support, private information, unsupported forecasts, missing facts, or invalid citations.
- Point-in-time-aware answer caching never caches abstentions.

### Research interfaces

- Filing differences use deterministic comparable periods and classify added/removed/changed passages.
- Company Facts preserve raw facts and map restrained canonical metrics.
- Research panels use the `fdre-panel-v3` feature contract.
- Every computed feature carries deterministic lineage with calculation version, parameters, exact source accessions, per-source availability timestamps, corpus snapshot identity, and SHA-256 lineage ID.
- Cross-sectional screens evaluate structured conditions before optional semantic retrieval and constrain evidence to exact PIT-selected accessions.
- Signal studies consume provider-neutral adjusted bars and retain selected feature lineage in events and experiment identity.
- Panel, screen, and signal lineage can be verified after export or replay.

See [`feature_lineage.md`](feature_lineage.md) for the stable lineage contract.

## Historical Universe v1

Historical Universe extends PIT correctness from filings/features to the **eligible security universe**.

```text
companies (SEC issuer / CIK)
        |
        | 1:N
        v
securities
        |
        +-----------------------------+
        |                             |
        v                             v
security_identity_periods       universe_memberships
symbol/name/exchange history    membership intervals
provenance + confidence         provenance + confidence
verification status             verification status
```

The separation between issuer and listed security is intentional: a CIK is not an investable security, and multiple share classes can coexist under one issuer. Tickers are time-varying attributes, not permanent IDs.

All historical identity and membership intervals use half-open `[effective_from, effective_to)` semantics. Strict snapshots fail closed on overlapping intervals, missing active identity, rejected evidence, or unresolved provisional membership.

The canonical HU design and milestone status live in [`historical_universe_v1.md`](historical_universe_v1.md).

## Point-in-Time model

`available_at` is the filing visibility boundary. Retrieval requires:

```text
document.available_at <= as_of
```

Panel generation requires every source document/fact used by a row to be available no later than the row timestamp. Every structured feature records its own `max_source_available_at`; lineage verification rejects future sources, incomplete timestamps, inconsistent availability ceilings, or hash mismatches.

Historical-universe snapshots add a second independent PIT condition:

```text
membership_effective_from <= as_of < membership_effective_to
```

with the corresponding security identity also valid at `as_of`.

Amendments compare to their original accession. Non-amended 10-K filings compare with the prior annual filing; 10-Q filings prefer the same quarter one year earlier.

## Reproducibility model

FDRE distinguishes deterministic structured lineage from provider-dependent semantic output.

- Feature lineage IDs fingerprint structured calculation/source identity.
- Universe snapshot IDs fingerprint exact membership/identity provenance.
- Screen lineage digests fingerprint the structured inputs evaluated across the PIT universe.
- Complete signal studies include selected accession/lineage identity in experiment keys and immutable manifests.
- Frozen benchmark datasets and first-run holdout artifacts are hash-pinned rather than overwritten.

Provider/reranker output is intentionally not misrepresented as deterministic structured lineage.

## Operations and failure behavior

- Batch ingest creates manifests with configuration, stage status/latency, before/after counts, provider usage, estimated cost, failures, and completion state.
- Quality audits report stale companies, missing forms, duplicate accessions, documents without chunks, chunks without embeddings, facts without documents, freshness, and coverage.
- GitHub Actions applies Alembic and runs batch/evaluation/research workflows.
- Railway applies Alembic in `preDeployCommand`; runtime startup only launches uvicorn.
- Market-data workflows use cache-first behavior, bounded provider retries/fallbacks, and fail-fast circuit breaking under rate limiting.
- Research outcomes may validly be `PROMOTE`, `REJECT`, or `INSUFFICIENT`; workflow success is not equated with statistical success.

## Cost model

FDRE keeps recurring infrastructure intentionally small:

- PostgreSQL replaces separate vector, lexical, trace, fact, cache, and experiment services while current SLOs remain achievable.
- SEC responses and market outcomes are cached.
- Embeddings are missing-only, batched, rate-limited, and retryable.
- Older research history should favor structured features/lineage and Parquet artifacts rather than bulk historical embeddings.
- Redis, Kafka, Elasticsearch/OpenSearch, Snowflake, distributed queues, and a separate feature store remain deferred until measured workload thresholds justify them.
- Historical bulk/cold artifacts may use cheap object storage only when storage growth warrants it.

Normal infrastructure target is **$10–15/month** with a **$20/month hard ceiling**.

## Structural constraints

- The current production S&P 500 seed is a current-constituent snapshot; historical studies remain exposed to survivorship/selection bias until HU-2+ reconstruction is integrated.
- Public historical-index evidence can be incomplete or contradictory; FDRE must preserve provenance and ambiguity instead of silently inventing dates.
- The interactive vector corpus is intentionally bounded; long research history does not imply embedding every historical paragraph.
- PDF parsing remains optional; the production corpus is SEC filing HTML.
- 8-K ingestion remains gated on explicit PIT research/evaluation value.
- Semantic provider output is not deterministic research lineage.

For current measured quality, latency, corpus size, and flagship-study status, use [`eval_results.md`](eval_results.md).
