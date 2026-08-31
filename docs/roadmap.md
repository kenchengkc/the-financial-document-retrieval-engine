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

**Status: ACTIVE / FAIL-CLOSED MATERIALIZATION IMPLEMENTED; PRODUCTION PROMOTION NOT COMPLETE.**

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

The first production-backed audit now characterizes the blocking gaps. R0/R1 created the current
security prerequisite and evidence-scoped aliases. Subsequent pinned, read-only measurements added
an independent 2010 anchor, exact ticker lineage, and historical component CIK evidence. The latest
component-history projection resolves **1,043 / 1,055 (98.86%)** target-window observations, but
that is a projection rather than a production write or a passed materialization gate. An
empty-schema rehearsal of the pinned materialization proved that the write path is atomic. The
follow-up audit found and fixed its source-validity error: lawcal `created_at` had been ignored,
projecting later ticker identities backward. The original **29 missing / 61 unexpected** mismatch
is now fully classified as 35 historical-to-terminal ticker aliases, 18 SEC-confirmed membership
gaps, one lawcal false positive, and one duplicated fja display lineage. The adjudicated count is
**500**, matching IVV's independently SEC-filed 2009-12-31 holdings schedule.

All 999 interval boundaries now have explicit decisions. **441 / 999** membership intervals have
corroborated start/end evidence, but only **181 / 999** are also safe under the point-in-time symbol
validity rule; the corrected materializer retains the other **818 / 999** as provisional. For
intervals starting in 2010+, the corresponding counts are **299 / 365** boundary-corroborated and
**170 / 365** strict-materializable. Strict resolution therefore still fails closed and production
tables remain unchanged.

The remaining sequence is:

1. attach dated ticker/CIK evidence to the 18 SEC-confirmed anchor membership gaps;
2. remediate the 66 post-anchor intervals whose membership boundaries remain unresolved and the
   129 whose membership is corroborated but point-in-time symbol identity is not;
3. publish the residual 12-row observation queue and retain every unresolved row as provisional;
4. replace the terminal-symbol comparison with an identity-safe 500-security starting snapshot;
5. rerun staged validation until strict and provisional snapshots match that anchor; and
6. explicitly apply the atomic write and rerun the canonical production promotion gate.

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

**Resolve the adjudicated HU-2 identity queue before production materialization.**

Do not start the decade-scale filing backfill yet. The old 533-versus-501 mismatch is fully
reconciled and every interval has a boundary/identity decision. Next resolve the 18 anchor
identities, 66 post-anchor boundary gaps, 129 post-anchor ticker-lineage gaps, and the residual
12-row observation queue, then satisfy the fail-closed staged promotion gate. HU-3 is implemented;
once HU-2's written state is credible, HU-4 can safely spend compute/storage on longer history.
