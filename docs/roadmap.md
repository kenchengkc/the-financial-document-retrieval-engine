# FDRE Roadmap — Hedge-Fund Research Infrastructure

FDRE is point-in-time financial research infrastructure for technically sophisticated research and engineering audiences. The product bar is not “interesting AI demo”; it is **credible research infrastructure**: correct historical data, reproducible experiments, auditable lineage, strong retrieval, statistically disciplined signal research, predictable latency, and explicit failure behavior.

> Status reviewed against `main` on **2026-08-30**.

## Product principles

A professional reviewer should be able to answer:

- Can I trust the information timestamp and universe eligibility?
- Can I reproduce the result from exact data/code identity?
- Can I trace every structured value back to its source filings?
- Are retrieval and research claims supported by frozen measurements?
- Are signal results evaluated out-of-sample with implementation costs and multiple-testing controls?
- Does the system fail closed when data, lineage, or provider state is ambiguous?
- Are infrastructure choices justified by measured bottlenecks rather than fashion?

Do **not** prioritize generic chatbot polish, autonomous-agent complexity, decorative dashboards, more LLM calls, or extra distributed infrastructure ahead of research correctness and reproducibility.

## Cost and architecture budget

| Component | Current policy |
| --- | --- |
| PostgreSQL / pgvector | authoritative production store for retrieval + research state |
| Railway API | bounded production compute |
| Vercel frontend | existing deployment |
| GitHub Actions | public CI / batch research |
| Embeddings / reranking | bounded provider spend; reranking optional |
| Historical bulk artifacts | Parquet/object storage only if needed |
| Normal monthly target | **$10–15** |
| Hard ceiling | **$20** |

**No new recurring service unless FDRE’s own measurements show the existing stack cannot meet a defined correctness, quality, latency, scale, or workflow requirement economically.**

Redis, Kafka, Elasticsearch/OpenSearch, Snowflake, a dedicated feature store, and distributed queues remain deferred behind measured triggers.

## Current state

### Complete / operational

- Point-in-time SEC filing ingestion with acceptance/availability boundaries.
- PostgreSQL lexical + vector hybrid retrieval over ~3.04M chunks.
- Citation-verified answer workflow with abstention and PIT-aware cache.
- Cross-sectional research screens with structured-first execution, exact filing evidence restriction, bounded semantic calls, and deployed HTTPS endpoint.
- `fdre-panel-v3` feature lineage with export/replay verification.
- Frozen retrieval and Cross-Sectional v2 benchmark contracts with immutable first-run holdout artifacts.
- Signal research primitives: event studies, Spearman IC, quantiles, long-short spreads, issuer-cluster bootstrap inference, multiple-testing correction, and experiment manifests.
- Flagship risk-churn acceleration study with precommitted walk-forward windows, purged unrealized outcomes, implementation-cost accounting, sector robustness, promotion gates, immutable artifacts, and honest `PROMOTE` / `REJECT` / `INSUFFICIENT` outcomes.
- Market-data cache/retry/circuit-breaker hardening.
- **Historical Universe HU-1:** stable security layer, time-varying identity/membership schema, provenance/confidence/verification state, deterministic PIT snapshot contract, Alembic migration, and tests.
- **Historical Universe HU-2:** production membership reconstruction, identity-safe 500-security
  starting anchor, explicit provisional queue, deterministic replay, and passed promotion gate.
- **Historical Universe HU-3:** DB-backed PIT universe API, deterministic snapshot IDs,
  constituent provenance, strict/provisional modes, JSON/Parquet export, replay and leakage tests,
  and research-panel composition.

### Current measured flagship state

The flagship infrastructure runs successfully, but the research conclusion remains **INSUFFICIENT_NOT_YET_REALIZED** for the primary 1:63 horizon at the latest evaluation time. Only one walk-forward fold is currently eligible and the statistical gate requires more independent OOS history. Do not reinterpret workflow success as alpha validation.

Current detailed metrics live in [`eval_results.md`](eval_results.md).

## Active milestone — Historical Universe v1

The current production S&P 500 seed is a **current-constituent snapshot**, so historical research remains exposed to survivorship/selection bias even when filings themselves are PIT-correct. Historical Universe v1 is therefore the highest-value next research milestone.

See [`historical_universe_v1.md`](historical_universe_v1.md) for the canonical design and acceptance criteria.

### HU-1 — Security master foundation

**Status: COMPLETE.**

Implemented:

- SEC issuer/CIK separated from stable listed-security identity;
- time-varying ticker/name/exchange periods;
- time-varying universe-membership intervals;
- provenance, confidence, and verification status;
- half-open `[effective_from, effective_to)` semantics;
- deterministic snapshot hashing;
- fail-closed overlap, missing-identity, rejected/provisional evidence behavior;
- migration and unit coverage.

### HU-2 — Membership reconstruction

**Status: COMPLETE (production promotion gate passed 2026-09-01).**

Build a reproducible evidence-reconciliation pipeline for historical index membership.

Required outputs:

1. source adapters that preserve raw event identity and observation time;
2. normalized add/remove/replacement events with announcement vs effective dates kept distinct;
3. historical ticker/name resolution to stable securities and SEC CIKs;
4. multi-source reconciliation with verified/provisional/rejected evidence;
5. explicit ambiguity instead of guessed dates;
6. deterministic interval materialization;
7. coverage/audit report for gaps, overlaps, unresolved identities, share-class ambiguity, and source disagreement;
8. current-date reconciliation against the existing S&P seed without using that seed as historical evidence.

**HU-2 promotion gate:** do not integrate historical membership into flagship research until the coverage audit can characterize where history is trustworthy and where it is provisional.

[Actions run `33462343599`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33462343599)
applied and validated the production materialization. It created 396 historical-only issuers, 6
current issuers, 483 securities, 1,004 identity periods, and 1,004 membership periods. Of the
memberships, 809 are verified and 195 remain explicitly provisional. The resulting production
state has 901 issuers, 985 common-stock securities, and 1,506 identity periods.

The original **29 missing / 61 unexpected** anchor mismatch is fully classified. The materializer
now uses an identity-safe 500-security anchor backed by IVV's SEC-filed 2009-12-31 holdings,
including dated ticker/CIK decisions for the 18 source gaps and the exact SEC-backed XOM CIK
correction. Strict and provisional snapshots both contain the expected 500 identities; replay is
deterministic; and identity overlaps, membership overlaps, and missing identity coverage are all
zero.

The final audit resolves **1,044 / 1,055 (98.96%)** target-window observations and publishes the
remaining 11 as unresolved/provisional. All 999 source intervals have explicit decisions. Of the
365 intervals starting in 2010+, 299 have verified membership boundaries and 66 remain
boundary-provisional. Completion means the production gate and fail-closed eligibility contract
passed; it does not turn those 66 boundaries or 11 residual identities into guessed facts.

Exact measured counts and the gate result live in [`eval_results.md`](eval_results.md); the gate
definition lives in [`historical_universe_v1.md`](historical_universe_v1.md).

### HU-3 — Universe API / SDK

**Status: COMPLETE (merged 2026-08-30).**

Strict PIT universe resolution is exposed through:

```python
fdre.universe("sp500", as_of="2020-03-20")
fdre.universe("sp500", as_of="2020-03-20", include_provisional=True)
```

Implemented:

- deterministic snapshot IDs;
- constituent-level source lineage;
- strict/provisional modes visible in outputs;
- JSON/Parquet export;
- replay verification;
- explicit future-membership leakage tests;
- composition with research-panel construction.

### HU-4 — 10–15 year research archive

Extend research depth without proportionally expanding the vector corpus.

Prefer:

```text
historical filing
  -> parse required sections/facts
  -> compute research features
  -> persist feature + exact lineage
  -> optional compressed/Parquet artifact
  -> no bulk embeddings unless justified
```

Acceptance criteria include reproducible market outcomes, Parquet panel export, measured before/after storage and runtime, and total recurring spend below the $20 ceiling.

### HU-5 — Institutional flagship rerun

Rerun the **unchanged precommitted** risk-churn acceleration study on the reconstructed historical universe and longer history.

Target:

- at least 4 statistically usable sealed OOS folds, preferably 4–6+;
- primary 1:63 outcome evaluable across multiple periods;
- secondary 1:21 and 1:126 horizons retained;
- 5/10/25/50 bp costs retained;
- sector/temporal robustness retained;
- universe snapshot identity included in the immutable experiment manifest;
- result remains honestly `PROMOTE`, `REJECT`, or `INSUFFICIENT`.

## After Historical Universe

Once HU makes the research dataset credible, the next highest-value investments are:

### Portfolio implementation layer

- monthly/weekly rebalance;
- sector-neutral and beta-neutral variants;
- turnover and 5/10/25/50 bp costs;
- max-weight/liquidity/ADV constraints;
- gross/net returns and signal decay.

### Falsification harness

- randomized signals and event dates;
- label permutation;
- deliberate timestamp-leak tests;
- placebo universes;
- alternate neutralizations;
- negative controls;
- explicit multiple-testing ledger.

### Researcher-facing SDK

Target ergonomics:

```python
panel = fdre.panel(...)
signal = fdre.signal(...)
study = fdre.walk_forward(...)
study.summary()
study.verify_lineage()
study.export(...)
fdre.replay("experiment_id")
```

Support Parquet + DuckDB/Polars interoperability without hiding the underlying data/lineage mechanics.

### Failure engineering and observability

Add formal stage timing, provider/database/network fault tests, cache-corruption tests, idempotent retry proofs, and repeatable SLO/load characterization only where they improve operational confidence.

### Harder evaluation

Expand reviewed retrieval/research cases with amendments, restatements, near-duplicates, issuer confusion, exact as-of boundaries, abstention, and hard negatives. Preserve sealed-holdout discipline.

## Immediate next step

**Begin HU-4's measured 10–15 year research archive.**

HU-2 and HU-3 are complete. Extend filing, feature, and market-outcome history without bulk
embedding the archive; preserve accession/availability lineage, export reproducible Parquet
panels, and measure storage/runtime/provider cost before scaling. The 66 provisional post-anchor
boundaries and 11-row identity queue remain explicit follow-up evidence work and must continue to
fail closed in strict snapshots.
