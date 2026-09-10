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
- independently verified 2010-01-01 through 2026-09-01 strict historical-universe eligibility;
- frozen and implemented HU-5 multi-class outcome mapping for simultaneous share classes;
- canonical historical-universe inspection/operations through one `scripts.research.universe` CLI;
- explicit research ownership for historical-universe, signals, experiments, and sealed OOS domains;
- market-data replay manifests, deterministic covering-cache reuse, and fail-closed adjusted-price parsing;
- historical filing research archive without unnecessary bulk embedding growth;
- CI covering typing, linting, tests, PostgreSQL/pgvector migrations/indexes, Docker, frontend build, and browser E2E paths;
- production container built non-editably, run as non-root, and smoke-tested in CI;
- process-scoped provider/reranker reuse, bounded hosted-provider HTTP pools, request concurrency protection, API statement timeouts, and a bounded issuer-reference cache;
- reproducible Python dependency resolution through the committed `uv.lock`.

The original unchanged flagship risk-churn acceleration run remains **`INSUFFICIENT`**, not promoted or rejected for alpha. That immutable run hit the predeclared multi-security ambiguity rule and remains preserved as originally executed. The multi-class outcome policy has since been frozen and implemented; any amended flagship evaluation must therefore use a new versioned experiment identity rather than rewriting the original result.

## Active priorities

### 1. Execute the amended flagship under the frozen multi-class policy

The outcome-mapping contract is no longer an open design problem. The next research step is to run the amended flagship path under the already-frozen point-in-time multi-class policy and preserve the original `INSUFFICIENT` root unchanged.

Acceptance criteria:

- use the frozen multi-class security-selection policy and pinned market symbology without outcome-driven changes;
- create a new versioned experiment identity rather than mutating the original run;
- preserve exact feature, filing, universe, market-data, and assumption lineage;
- produce an honest terminal `PROMOTE`, `REJECT`, or `INSUFFICIENT` result under the predeclared gates;
- register, bundle, and independently verify the resulting artifact chain before making a research claim.

### 2. Improve retrieval quality under a clean evaluation lifecycle

Current public retrieval and Cross-Sectional holdouts are published historical benchmarks. Future untouched claims require newly sealed, access-controlled holdouts under the benchmark lifecycle policy.

Priorities:

- improve generic semantic/paraphrase recall without weakening PIT filters or citation grounding;
- preserve exact-vs-ANN validation when changing vector/index configuration;
- measure retrieval changes on development data first, then evaluate once on a newly sealed holdout;
- keep latency/cost measurements alongside quality metrics.

Do not optimize directly against the published historical holdout and then describe the result as unseen performance.

### 3. Finish repository surface-area cleanup without inventing architecture

The target structure is a small deployed core, reusable domain packages, thin operational entry points, and archived run history. Historical-universe, signals, experiments, and OOS now have explicit ownership; remaining changes should be justified by real coupling rather than directory symmetry.

Priorities:

- keep large operational scripts thin by moving genuinely reusable logic into existing domain packages;
- retire temporary compatibility imports only after active callers have migrated and architecture checks can enforce the canonical path;
- reduce giant frontend files through component ownership, then split global CSS only where selectors have a clear route/component owner;
- keep `panel.py` and `screen.py` at their current cross-cutting boundary unless a concrete ownership split improves the dependency graph;
- keep active docs focused on contracts/current state and move dated forensic notes to `docs/archive/`.

Refactors must preserve existing tests, experiment identities where applicable, and data/research contracts.

### 4. Optimize production from measurements, not from an infrastructure wish list

The previously listed client reuse, hosted-provider connection pooling, process-level request protection, issuer-reference caching, and dependency locking are implemented. Further runtime work should start from measured production bottlenecks.

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
- [`research/historical-universe/final-identity-closure.md`](research/historical-universe/final-identity-closure.md) — identity-closure provenance
- [`research/historical-universe/flagship-rerun-2026-09-06.md`](research/historical-universe/flagship-rerun-2026-09-06.md) — frozen unchanged flagship rerun
