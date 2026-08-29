# Cross-Sectional Screen Latency — Historical Diagnostic

> Historical performance note. Current production latency belongs in [`docs/eval_results.md`](../eval_results.md); current architecture and next performance work belong in [`docs/architecture.md`](../architecture.md) and [`docs/roadmap.md`](../roadmap.md).

## Context

This note records the profiling work that followed the frozen Cross-Sectional v2 holdout. At the time, the deployed production API did not yet expose `/research/screen`, so executor measurements and deployed-route measurements had to be kept separate.

## Stage profile before optimization

A five-case development sample used the production Neon database, Voyage `voyage-4-large` 512-D embeddings, PostgreSQL sparse retrieval, no reranker, and two repetitions per case.

| Task | Mean total | Mean panel | Mean semantic search | Mean evidence filter |
| --- | ---: | ---: | ---: | ---: |
| Structured | 2.47 s | 2.47 s | 0 | 0 |
| Change | 1.94 s | 1.94 s | 0 | 0 |
| Semantic | 3.39 s | 2.12 s | 1.21 s | 0.06 s |
| Semantic + structured | 2.40 s | 1.74 s | 0.60 s | 0.06 s |

Panel construction was the dominant stage. `execute_research_screen` knew which feature families were required but created a panel query without a feature subset, causing the full default panel to be computed.

## Optimization

The screen was changed to request only the feature families required by its conditions and ranking. A semantic-only screen requests only `filing_timing`, preserving filing identity/timestamp lineage without loading unrelated filing text or XBRL facts. `build_research_panel` also skips `DocumentElement` and `FinancialFact` loading when the selected feature set does not require those storage families.

## Measured executor result

| Task | Mean total | Mean panel | Change in mean panel |
| --- | ---: | ---: | ---: |
| Structured | **0.31 s** | **0.31 s** | **-87.6%** |
| Change | **0.22 s** | **0.22 s** | **-88.8%** |
| Semantic | **2.22 s** | **0.62 s** | **-71.0%** |
| Semantic + structured | **1.74 s** | **0.82 s** | **-53.1%** |

The complete 28-case frozen development benchmark was then rerun on the optimized executor path and preserved zero PIT leakage, 100% condition correctness, and bounded semantic calls.

## Why this file is archived

The production route is now deployed and later HTTPS measurements supersede the deployment-parity problem described here. The durable engineering lesson is that FDRE profiled the measured bottleneck and removed unnecessary panel work before considering Redis, Elasticsearch, or another service. Current production numbers are maintained only in `docs/eval_results.md` to avoid metric drift.
