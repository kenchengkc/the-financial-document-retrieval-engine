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
- historical filing research archive without unnecessary bulk embedding growth;
- CI covering typing, linting, tests, PostgreSQL/pgvector migrations/indexes, Docker, frontend build, and browser E2E paths;
- production container built non-editably, run as non-root, and smoke-tested in CI;
- explicit API readiness, request bounds, and PostgreSQL connection-pool policy.

The latest unchanged flagship risk-churn acceleration run remains **`INSUFFICIENT`**, not promoted or rejected for alpha. The verified universe passed its gate, but issuer-level filings for one multi-security issuer could not be mapped unambiguously to a single security under the predeclared fail-closed rule. That result is preserved rather than guessed through.

## Active priorities

### 1. Close the multi-security outcome-mapping contract

Define a versioned, point-in-time rule for research outcomes when a filing issuer has multiple simultaneously active securities. The rule must be specified before examining amended-run return results and must preserve share-class identity rather than silently choosing a ticker.

Acceptance criteria:

- deterministic security selection or explicit ambiguity;
- source/provenance for the mapping rule;
- no outcome information used to select the rule;
- replay tests around simultaneous share classes and ticker changes;
- amended flagship run uses a new versioned experiment identity and leaves the original frozen run unchanged.

### 2. Improve retrieval quality under a clean evaluation lifecycle

Current public retrieval and Cross-Sectional holdouts are published historical benchmarks. Future untouched claims require newly sealed, access-controlled holdouts under the benchmark lifecycle policy.

Priorities:

- improve generic semantic/paraphrase recall without weakening PIT filters or citation grounding;
- preserve exact-vs-ANN validation when changing vector/index configuration;
- measure retrieval changes on development data first, then evaluate once on a newly sealed holdout;
- keep latency/cost measurements alongside quality metrics.

Do not optimize directly against the published historical holdout and then describe the result as unseen performance.

### 3. Finish production runtime hardening

Keep the API small and explicit while removing request-path construction overhead.

Priorities:

- reuse expensive embedding/reranking/provider clients by configuration;
- use persistent HTTP connection pools for hosted providers;
- make provider rate limits reflect process-level concurrency rather than per-request object lifetime;
- cache the immutable issuer/alias lookup used by query preprocessing with an explicit refresh/invalidation contract;
- lock Python dependency resolution reproducibly;
- retain durable retrieval/audit traces while optimizing persistence only when measurements justify it.

### 4. Reduce repository surface area without reducing rigor

The target structure is a small deployed core, reusable domain packages, thin operational entry points, and archived run history.

Priorities:

- move reusable logic out of large `scripts/` entry points into `src/fdre/`;
- consolidate historical-universe operations behind a small coherent CLI;
- split `src/fdre/research/` into clear universe, signals, panels, experiments, and OOS domains;
- reduce giant frontend files and global CSS through route/component ownership and verified dead-style removal;
- keep active docs focused on contracts/current state and move dated forensic notes to `docs/archive/`.

Refactors must preserve existing tests, experiment identities where applicable, and data/research contracts.

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
