# FDRE Roadmap — Research Infrastructure

FDRE is point-in-time financial research infrastructure. The engineering bar is **credible, reproducible research**, not feature count: correct information timing, survivorship-aware universes, source lineage, measured retrieval quality, falsifiable research workflows, predictable operations, and explicit failure behavior.

Detailed historical execution notes from the previous roadmap are preserved in [`archive/roadmap-2026-09-08.md`](archive/roadmap-2026-09-08.md). Current measurements belong in [`evaluations/eval_results.md`](evaluations/eval_results.md); benchmark methodology and reveal rules belong in [`evaluations/eval_plan.md`](evaluations/eval_plan.md) and [`evaluations/holdout_policy.md`](evaluations/holdout_policy.md).

## Engineering principles

A reviewer should be able to establish quickly that:

- information is filtered by when it was actually available;
- historical universe membership and security identity are not inferred from current constituents;
- structured values and research features retain exact source lineage;
- benchmark and experiment inputs are frozen or versioned deliberately;
- published benchmarks are not misrepresented as future unseen holdouts;
- statistical failures and insufficient samples are reported rather than optimized away;
- ambiguous identity, lineage, or evidence fails closed;
- infrastructure complexity is added only when measurements justify it.

PostgreSQL/pgvector remains the system of record. Railway, Vercel, GitHub Actions, and bounded model-provider usage remain the operating stack. New recurring infrastructure should have a measured correctness, quality, latency, scale, or cost justification.

## Current platform state

The production/research core is operational:

- point-in-time SEC filing ingestion using acceptance/availability boundaries;
- PostgreSQL lexical + pgvector hybrid retrieval and optional reranking;
- citation-verified extractive answers with abstention and PIT-aware caching;
- typed Company Facts, research panels, cross-sectional screens, and filing comparisons;
- persisted retrieval traces, experiment manifests, market-data caches, and reproducible signal-study workflows;
- deterministic historical-universe identity and membership with strict/provisional evidence modes;
- independently verified **6,088 / 6,088** strict-eligible historical-universe days from 2010-01-01 through 2026-09-01;
- frozen and implemented HU-5 multi-class outcome mapping for simultaneous share classes;
- canonical historical-universe inspection/operations through one `scripts.research.universe` CLI;
- explicit research ownership for historical-universe, signals, experiments, and sealed OOS domains;
- market-data replay manifests, deterministic covering-cache reuse, and fail-closed adjusted-price parsing;
- historical filing research archive without unnecessary bulk embedding growth;
- CI covering typing, linting, tests, PostgreSQL/pgvector migrations/indexes, Docker, frontend build, and browser E2E paths;
- production container built non-editably, run as non-root, and smoke-tested in CI;
- process-scoped provider/reranker reuse, bounded hosted-provider HTTP pools, request concurrency/rate protection, API statement timeouts, and bounded issuer-reference caching;
- direct browser verification of filing comparison, financial facts, and point-in-time dataset preview/export contracts;
- reproducible Python dependency resolution through the committed `uv.lock`.

The flagship risk-churn acceleration study now has **two separate immutable `INSUFFICIENT` terminal records**:

1. the unchanged post-HU-5-closure rerun failed closed on `ambiguous_security_mapping` before outcome evaluation;
2. the separately versioned multi-class amended rerun passed the frozen identity and market-symbology preflight, then failed closed on `multiclass_component_outcome_unavailable` because three predeclared Alphabet benchmark horizons were not yet realized.

Neither run is a `REJECT` or `PROMOTE` result. The second result closes the methodology/symbology design work for this blocker: the next flagship rerun is waiting on outcome observability, not another methodology amendment.

## Active priorities

### 1. Hold the amended flagship methodology fixed until all frozen horizons are observable

The multi-class issuer-outcome policy and market-provider symbology contract are frozen. The amended 2026-09-06 execution is `INSUFFICIENT` solely because its latest required benchmark endpoints are right-censored in the frozen market cache.

Acceptance criteria for the next canonical rerun:

- do **not** drop recent Alphabet events, shorten horizons, substitute benchmark dates, select one share class post hoc, or renormalize around unavailable outcomes;
- wait until every predeclared benchmark/component endpoint is actually present in the refreshed market cache;
- refresh through the existing provider/symbology contract and rerun the unchanged preflight first;
- execute the unchanged amended study only after the preflight confirms complete frozen-horizon availability;
- preserve the prior unchanged and amended `INSUFFICIENT` artifacts as immutable historical records;
- create a new run artifact/provenance chain for the later execution and report its terminal `PROMOTE`, `REJECT`, or `INSUFFICIENT` state without reinterpretation.

The latest currently blocking `1:126` endpoint is expected around **2027-01-22**, but the real gate is observed endpoint availability in the refreshed benchmark/component cache, not the calendar estimate.

### 2. Improve retrieval quality under a clean evaluation lifecycle

Current public retrieval and Cross-Sectional holdouts are published historical benchmarks. Future untouched claims require newly sealed, access-controlled holdouts under the benchmark lifecycle policy.

Priorities:

- improve generic semantic/paraphrase recall without weakening PIT filters or citation grounding;
- preserve exact-vs-ANN validation when changing vector/index configuration;
- measure retrieval changes on development data first, then evaluate once on a newly sealed holdout;
- keep latency/cost measurements alongside quality metrics.

Do not optimize directly against the published historical holdout and then describe the result as unseen performance.

### 3. Maintain repository boundaries; refactor only when coupling demonstrates a need

The broad ownership cleanup is complete enough to stop. Historical-universe, signals, experiments, OOS, and the retrieval research workflows have explicit boundaries, and the remaining small frontend/routes do not justify decomposition merely for file-size symmetry.

Going forward:

- keep operational entry points thin when reusable logic genuinely emerges;
- retire compatibility paths only after active callers have migrated and architecture checks can enforce the canonical path;
- split frontend/CSS ownership only when a real component or route boundary is obscured;
- keep `panel.py` and `screen.py` at their current cross-cutting boundary unless a concrete dependency problem appears;
- keep active docs focused on current contracts/results and move dated forensic history to `docs/archive/`.

Do not continue broad repository cleanup as an end in itself.

### 4. Optimize production from measurements, not from an infrastructure wish list

Client reuse, hosted-provider connection pooling, process-level request protection, issuer-reference caching, request-scoped PostgreSQL timeouts, and dependency locking are implemented and acceptance-tested. Further runtime work should start from measured production bottlenecks.

Priorities:

- use bounded retrieval telemetry and request traces to identify the next material latency or failure source;
- profile semantic retrieval and reranking tail latency before changing provider/index configuration;
- preserve process-level provider budgets and request rejection behavior while tuning concurrency;
- keep durable retrieval/audit traces while optimizing persistence only when measurements justify it;
- add no recurring service unless a measured correctness, quality, latency, scale, or cost problem cannot be solved cleanly in the current stack.

## Research promotion rules

Signal workflows are experiments, not demos. Promotable research must retain:

- exact PIT feature and outcome lineage;
- predeclared horizons and split logic;
- purging of unrealized development outcomes;
- multiple-testing-aware gates;
- turnover and explicit transaction-cost assumptions;
- sector/temporal robustness diagnostics;
- immutable code/config/data identity;
- honest terminal outcomes of `PROMOTE`, `REJECT`, or `INSUFFICIENT`.

A successful workflow run is not evidence of alpha.

## Explicitly deferred

Unless measurements establish a concrete need, FDRE does **not** need:

- Redis or a distributed cache;
- Kafka or a distributed queue;
- a separate vector/search service;
- Snowflake or a dedicated analytics warehouse;
- a feature-store product;
- autonomous/open-ended agent loops;
- additional model calls solely for product appearance.

Likewise, do not simplify away the controls that provide the strongest research signal: point-in-time semantics, provenance, fail-closed identity behavior, immutable first-run artifacts, benchmark discipline, and comprehensive tests.

## Canonical references

- [`architecture/system.md`](architecture/system.md) — deployed component/data-flow design
- [`architecture/feature_lineage.md`](architecture/feature_lineage.md) — feature/source lineage contract
- [`evaluations/eval_plan.md`](evaluations/eval_plan.md) — evaluation methodology
- [`evaluations/holdout_policy.md`](evaluations/holdout_policy.md) — benchmark visibility lifecycle
- [`evaluations/eval_results.md`](evaluations/eval_results.md) — current and frozen measurements
- [`research/historical_universe.md`](research/historical_universe.md) — historical-universe contract
- [`research/historical-universe/final-identity-closure.md`](research/historical-universe/final-identity-closure.md) — HU-5 identity-closure provenance and durable evidence locator
- [`research/historical-universe/flagship-rerun-2026-09-06.md`](research/historical-universe/flagship-rerun-2026-09-06.md) — frozen unchanged flagship rerun
- [`research/historical-universe/flagship-amended-rerun-2026-09-06.md`](research/historical-universe/flagship-amended-rerun-2026-09-06.md) — frozen amended multi-class rerun and observability gate
