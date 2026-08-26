# Cross-Sectional Screen Latency

This note records the measured latency follow-up after the frozen Cross-Sectional v2 holdout. The goal is to keep latency work evidence-driven: profile the existing path, optimize the dominant stage, and avoid adding infrastructure unless measurement requires it.

## Deployment parity finding

On 2026-08-26, ten POST requests covering structured, change, semantic, and semantic+structured plans were sent to the production API origin used by the web app:

```text
https://api.thefdre.com/research/screen
```

All ten returned HTTP 404. Therefore the previously reported Cross-Sectional v2 holdout latency is **not** a canonical deployed `/research/screen` route SLO. It measures the production screen executor against the production Neon/provider environment. A real route p50/p95 must be measured only after the Railway API deployment exposes `/research/screen`.

This finding does not justify a new deployment service or monitoring dependency. It is a deployment-parity gate: deploy the already-merged API route, then measure it directly.

## Stage profile before optimization

A five-case development sample used the same production Neon database, Voyage `voyage-4-large` 512-D embeddings, PostgreSQL sparse retrieval, no reranker, and two repetitions per case.

| Task | Mean total | Mean panel | Mean semantic search | Mean evidence filter |
| --- | ---: | ---: | ---: | ---: |
| Structured | 2.47 s | 2.47 s | 0 | 0 |
| Change | 1.94 s | 1.94 s | 0 | 0 |
| Semantic | 3.39 s | 2.12 s | 1.21 s | 0.06 s |
| Semantic + structured | 2.40 s | 1.74 s | 0.60 s | 0.06 s |

The panel was the clear bottleneck. `execute_research_screen` knew which feature families were required by its structured conditions/ranking, but it created a `ResearchPanelQuery` without a feature subset. An empty panel feature list means "compute the full default panel", including text-derived and XBRL-derived features the screen did not use.

## Optimization

The screen now requests only the feature families required by its conditions and numeric ranking. A semantic-only screen requests only `filing_timing`, which preserves filing identity/timestamp lineage without loading filing text or XBRL facts.

`build_research_panel` also skips `DocumentElement` and `FinancialFact` loading when the explicit selected feature set does not require those storage families. Default panel calls remain unchanged: an empty `ResearchPanelQuery.features` still computes the full default panel.

No latest-filing-only panel abstraction was added. The first measured optimization was sufficient, so a more invasive query path is not justified by the current benchmark.

## Measured result

The same five-case/two-repeat production-executor profile after feature pruning measured:

| Task | Mean total | Mean panel | Change in mean panel |
| --- | ---: | ---: | ---: |
| Structured | **0.31 s** | **0.31 s** | **-87.6%** |
| Change | **0.22 s** | **0.22 s** | **-88.8%** |
| Semantic | **2.22 s** | **0.62 s** | **-71.0%** |
| Semantic + structured | **1.74 s** | **0.82 s** | **-53.1%** |

Semantic latency now primarily comes from retrieval/provider work rather than panel construction. The semantic sample had visible cold/provider variance, so the small five-case profile should be treated as stage attribution, not a final SLO.

## Frozen development verification

The complete 28-case frozen Cross-Sectional v2 development benchmark was then rerun on the optimized executor path:

| Metric | Result |
| --- | ---: |
| Issuer Recall@1 / @3 / @5 | **0.929 / 0.964 / 1.000** |
| Evidence Recall@1 / @3 / @5 | **0.500 / 0.556 / 0.611** |
| Condition correctness/source grounding | **15/15 (100%)** |
| Exact lineage replay | **15/15 (100%)** |
| Strict condition grounding | **15/15 (100%)** |
| PIT leakage | **0%** |
| Mean / max semantic calls | **0.643 / 1** |
| Executor p50 / p95 | **0.633 s / 1.456 s** |
| Semantic-only p95 | **1.524 s** |
| Semantic + structured p95 | **0.983 s** |
| Structured-only p95 | **0.359 s** |
| Change-screen p95 | **0.686 s** |

The benchmark used the unchanged frozen development dataset SHA `b3d0b17bd2da7ccaaf6cb655dff7de6e91c9506d5a61e15a19f0d049f8644571`, corpus snapshot `388fe80d07d5bd6e`, 3,204 filings, and 3,039,403 chunks/embeddings.

## Next gate

Do not optimize the semantic provider path from this small profile alone. The next latency action is:

1. deploy the current Railway API so `/research/screen` is actually present;
2. run direct HTTP structured and semantic workloads against that route;
3. record real end-to-end p50/p95 and route overhead;
4. profile retrieval further only if the deployed semantic p95 still misses the target.

Until step 1 is complete, executor measurements should be labeled executor/production-data latency rather than a deployed route SLO.
