# FDRE Research Infrastructure and Quant Research Engineering Roadmap

## Positioning

FDRE demonstrates **Research/Data Engineering** and **Quant Research Engineering**: reliable
research datasets, reproducible experiments, point-in-time correctness, and systems that support
researchers. It is not presented as a trading strategy or low-latency system.

## Implemented

### Phase 19: Retrieval correctness and performance

- Exact aliases and ticker boundaries replace substring detection.
- Broad thematic queries no longer infer accidental ticker filters.
- PostgreSQL GIN full-text and partial Voyage-512 HNSW indexes.
- Compound metadata indexes and cached coverage.
- PostgreSQL query-plan tests in CI.

Production indexes are deployed. Latency distributions and ANN recall remain to be measured.

### Phase 20: Reproducible retrieval benchmark

- Stable evidence references use accession, section, normalized quotation, and fingerprint.
- 80/40 development/holdout contract with category and reviewer validation.
- Sparse, dense, hybrid, and hybrid-plus-reranker comparison.
- Recall, MRR, nDCG, table recall, citation, abstention, entity, latency, and cost reporting.
- Corpus snapshot, Git SHA, parser, embedding, and retrieval configuration metadata.

The reviewed 120-question dataset and holdout run remain unpublished until review is complete.

### Phase 21: Point-in-time and temporal corpus

- Indexed SEC acceptance time, `available_at`, amendments, and accession lineage.
- `as_of` and acceptance-range filters in dense and sparse SQL.
- Fixed 50-company research universe with 3-annual/8-quarter depth controls.
- Comparable-period selection and filing differences.

### Phase 22: Structured XBRL facts

- Company Facts ingestion for indexed accessions.
- Raw taxonomy facts plus canonical revenue, operating income, net income, EPS, cash, debt,
  shares, capex, and operating cash flow.
- Unit/context/fiscal-period normalization, duplicate keys, amendments, and restatements.
- Typed point-in-time fact queries with narrative evidence.

### Phase 23: Research-ready feature dataset

- Versioned issuer-period panel with filing, novelty, risk-change, density, topic, timing, growth,
  and margin features.
- Source accessions, feature provenance, corpus snapshot, calculation version, and leakage checks.
- JSON, CSV, and Parquet output.

### Phase 24: Event-study harness

- Provider-neutral adjusted-bar CSV/Parquet input.
- Acceptance-to-next-session alignment and configurable windows.
- Benchmark-adjusted returns, deterministic bootstrap intervals, adjusted significance, and
  walk-forward splits.
- Persisted experiment configuration, dataset/feature versions, code SHA, and observations.

### Phase 25: Analyst and researcher workflows

- Filing comparison.
- Structured/narrative fact fusion.
- Issuer-diversified thematic scans.
- Point-in-time search.
- Research-panel export.
- Deliberate abstention for forecasts, private information, and unsupported claims.

### Phase 26: Data quality and operations

- Ingestion-run manifests with stage counts, failures, retry field, latency, provider usage, and
  estimated cost.
- Freshness, expected-form, duplicate, chunk, embedding, and fact integrity audits.
- Daily incremental checks, migration-before-ingest, and post-run audits in GitHub Actions.
- Serialized production ingestion across scheduled, S&P 500, research backfill, and Company Facts
  workflows with bounded batch controls.

### Phase 27: Recruiter-facing evidence

- Working search remains the first screen.
- About page presents verified corpus scale, system guarantees, and five research workflows.
- The query workspace prioritizes the answer and filing evidence while keeping scores and traces
  available for inspection.
- README and architecture use verified numbers only; one-off demo and resume documents were
  removed.

## Remaining Production Work

Completed on 2026-07-09 (see `docs/eval_results.md`):

1. Remeasured latency — single-name p95 **1.95 s** and cross-sectional p95 **1.74 s** both pass.
2. Exact-versus-ANN Recall@10 — mean **1.00**, max delta **0.00** (pass).
3. Frozen reviewed 120-question benchmark; holdout Hybrid Recall@10 **0.375** after automated
   paraphrase/regrounding (aspirational 0.85 still needs human labels).
4. Research 50 backfill and Company Facts workflows already completed (Jun 20).
5. AWK / AXON / AXP indexed; unchunked GOOG filings remediated.
6. FDXF verified blocked: SEC CIK `0002082247` has Form 3/4/8-K only — no 10-K/10-Q yet.

Still open (not fully automatable):

1. Human-authored holdout paraphrases until Recall@10 ≥ 0.85 (and related quality gates).
2. Ingest FDXF when its first 10-Q/10-K appears on EDGAR.

## Deferred

- 8-K ingestion until point-in-time evaluation passes.
- Historical index constituent membership.
- OpenSearch, Kafka, distributed queues, and extra databases.
- Live trading, execution simulation, portfolio optimization, and alpha claims.
- Paid answer generation without a measured benchmark improvement.
