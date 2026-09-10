# Evaluation Results

This is the canonical active record of FDRE measurements. Methodology and freeze rules live in [`eval_plan.md`](eval_plan.md), and benchmark visibility rules live in [`holdout_policy.md`](holdout_policy.md). The longer pre-handoff results record, including dated Historical Universe remediation checkpoints and earlier flagship diagnostics, is preserved unchanged in [`../archive/eval_results-2026-09-10-pre-handoff.md`](../archive/eval_results-2026-09-10-pre-handoff.md).

Historical results are immutable. A later run may supersede the current operational state, but it does not rewrite an earlier measured result or convert an `INSUFFICIENT` result into evidence for promotion or rejection.

## Current production snapshot

Latest documented production scale:

| Metric | Value |
| --- | ---: |
| S&P 500 primary tickers indexed | **499 / 499** |
| SEC 10-K/10-Q filings | **3,204** |
| Parsed chunks | **3,039,403** |
| Embedded chunks | **3,039,403** |
| Embedding model | Voyage `voyage-4-large`, 512-d `halfvec` |
| Approximate DB size after `halfvec` migration | **11 GB** |

The current-constituent seed remains a present-day catalog input, not a survivorship-free historical universe. Historical membership and security identity are handled by Historical Universe v1 and are not backfilled from current constituents.

## Production Cross-Sectional v2 development replay

The frozen 28-case Cross-Sectional v2 development suite was executed through the deployed `POST /research/screen` HTTPS path.

| Metric | Production result |
| --- | ---: |
| Successful requests | **28 / 28** |
| Issuer Recall@1 | **0.929** |
| Issuer Recall@3 / @5 | **1.000 / 1.000** |
| Evidence Recall@1 | **0.833** |
| Evidence Recall@3 / @5 | **0.944 / 0.944** |
| Condition correctness/source grounding | **100%** |
| Exact lineage replay | **100%** |
| Strict condition grounding | **100%** |
| PIT leakage | **0%** |
| End-to-end p95 | **1.86 s** |

This remains the preferred production-screen headline because it measures the deployed path rather than an executor-only probe.

## Cross-Sectional v2 sealed holdout — immutable first reveal

The 14-case sealed holdout was first executed on **2026-08-26** after construction without screen/retrieval execution. Its first-run artifact remains frozen at `data/evals/results/cross-sectional-v2-holdout-first-run/`.

| Metric | First holdout result |
| --- | ---: |
| Issuer Recall@1 | **1.000 (14/14)** |
| Issuer Recall@3 / @5 | **1.000 / 1.000** |
| Exact evidence Recall@1 / @3 / @5 | **0.778 / 0.778 / 0.778** |
| Strict condition grounding | **0.0% (0/8)** |
| PIT leakage | **0%** |
| p50 / p95 latency | **3.15 s / 6.15 s** |
| Max semantic calls | **1** |

The frozen `0/8` strict score is not an issuer-ranking failure. Post-freeze diagnosis showed correct selected accessions, structured values, source-accession chains, and pass/fail decisions; the mismatch was in snapshot-scoped lineage IDs created under a different panel snapshot context. The frozen result remains unchanged. See `../archive/cross_sectional_condition_replay.md` for the historical diagnosis.

## Retrieval benchmark

The reviewed retrieval contract contains 120 questions: 80 development and 40 historical holdout questions. That published holdout is no longer an untouched future holdout.

### Historical holdout retrieval

| Variant | Recall@10 | MRR | Table Recall@10 |
| --- | ---: | ---: | ---: |
| Dense only | 0.350 | 0.192 | 0.500 |
| Sparse only | 0.250 | 0.068 | 0.000 |
| **Hybrid** | **0.375** | **0.164** | **0.500** |

Hybrid Recall@10 remains below the aspirational **0.85** gate. Do not describe this published benchmark as production-ready semantic coverage or as a future unseen holdout.

### Content-grounded ablation continuity

| Variant | Recall@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: |
| Baseline | 0.152 | 0.086 | 0.102 |
| **Shipped multi-query** | **0.212** | **0.134** | **0.153** |
| + neighbor expansion | **0.242** | — | — |

Multi-query expansion remains the shipped default because it produced a measured roughly 40% Recall@5 lift on the grounded ablation.

### Exact versus ANN

| Metric | Result |
| --- | ---: |
| ANN Recall@10 | **1.00** |
| Max delta from exact | **0.00** |

The measured filtered-search ranking showed no observed top-10 degradation from the HNSW ANN path under the benchmark configuration.

## Storage and cached-answer measurements

Migrating embeddings from full precision to PostgreSQL `halfvec` reduced the database from approximately **15 GB to 11 GB (~27%)** with no observed top-10 ranking change in the exact-versus-ANN check above.

Verified point-in-time-aware answer-cache hits are approximately **44 ms** in the documented production measurement. Abstentions are not cached.

## Historical Universe v1 / HU-5 identity state

Historical Universe identity closure is complete for the flagship research window. The merged gate and independent identity-strict audit both report **6,088 / 6,088** eligible calendar days from **2010-01-01 through 2026-09-01**, with **0** invalid days and **0** relevant provisional identities. The canonical gate manifest is `95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8`.

The production apply and independent-audit artifact is `9971101844` from Actions run `33971576262`, archive SHA-256 `ac326c69c936a859a6af0155653d0c55e3ca4464b5cf130004f77223e0dbf0cc`. That unchanged closure-evidence ZIP and checksum were durably preserved in `ghcr.io/kenchengkc/fdre-hu5-closure-evidence` at registry digest `sha256:05c5c9e7f3c3ccbe3986948b1950fd0ec957fc38256a4243626e44d3944d768b`. See [`../research/historical-universe/final-identity-closure.md`](../research/historical-universe/final-identity-closure.md) for the complete provenance and read-only verification procedure.

This identity closure is a prerequisite result, not signal evidence.

## Flagship risk-churn acceleration study

The flagship is a precommitted expanding walk-forward experiment. Workflow success means the pipeline executed and preserved a terminal state; it does **not** imply statistically promotable alpha.

### Frozen unchanged post-closure rerun

The first flagship rerun after HU-5 identity closure is preserved independently and remains immutable.

| Field | Frozen value |
| --- | --- |
| Actions run | `34003895773` |
| Code SHA | `a969eb3b6e8d246831047b5dd9a103de607d404f` |
| Artifact | `9980361918` (`flagship-risk-churn-acceleration-34003895773`) |
| Artifact SHA-256 | `a2a2ba816d5e6a4bbf9652c0cf0832313ce8d8c5375869b7cf4cdc8fa7647997` |
| Result | **`PRIMARY_RESULT=INSUFFICIENT`** |
| Reason | `ambiguous_security_mapping` |
| Experiment / insufficiency manifest | `72cab4ff9226b1d78bf721fd3f3ee81a14cf485b16b8686f8e6bd1c11f02cc68` |
| Scored events / eligible folds / OOS events | **0 / 0 / 0** |

Exactly 14 otherwise eligible Alphabet issuer-level filings mapped to more than one simultaneously active listed security. The unchanged methodology failed closed before security-level outcomes were evaluated. This result supplies no evidence for `PROMOTE` or `REJECT` and must not be rewritten after the later multi-class amendment. Full frozen record: [`../research/historical-universe/flagship-rerun-2026-09-06.md`](../research/historical-universe/flagship-rerun-2026-09-06.md).

### Frozen amended multi-class rerun

A separately versioned multi-class issuer-outcome policy and frozen provider-symbology layer were then completed **before** another outcome evaluation. The first canonical amended run is also immutable.

| Field | Frozen value |
| --- | --- |
| Canonical workflow | `flagship-risk-churn-acceleration.yml` |
| Actions run / job | `34055143306` / `101545611259` |
| Trigger | push to `main` from PR `#111` |
| Code / merge SHA | `c0d455086cdf533eb27bedd8b9c07586bccf667b` |
| Effective research inputs | `max_tickers=250`, `min_documents=6`, `max_uncached_market_fetches=300` |
| Market mode | **cache-only** |
| Market symbology profile | `fdre-hu5-market-symbology-v1` |
| Restored market cache key | `fdre-market-Linux-34016265578` |
| Issuer-outcome policy | `fdre-hu5-multiclass-outcome-v1` |
| Outcome mapping | `17c668c61da943beb48c9f3dd58325ab7222bb3836d21774eacfa07b0f704cd2` |
| Market symbology manifest | `89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328` |
| Preflight ID | `9218bc6b2de26a9f7bd993964c7ab3ffbe9f6a979b05b0dbcdd72bbc7bfeee86` |
| Result | **`PRIMARY_RESULT=INSUFFICIENT`** |
| Reason | `multiclass_component_outcome_unavailable` |
| Experiment / insufficiency manifest | `3ddccc0ecbb4a51f7b938a030f2ec9526aef33dc6e5419ba5f057e24f8ece34a` |
| Primary observations / OOS events / eligible folds / scored events | **0 / 0 / 0 / 0** |

The pre-outcome symbology gate passed: **6,088 / 6,088** strict eligible days, **3,996** resolved filing events, **14** multi-class events, **0** missing historical symbols, and the restricted `KFT -> MDLZ` validation passed. Return evaluation was not performed by the preflight.

The terminal insufficiency is caused by exactly three not-yet-realized benchmark horizons:

| Accession | Event date | Window | Reason |
| --- | --- | --- | --- |
| `0001652044-26-000048` | 2026-04-30 | `1:126` | `benchmark_window_unavailable` |
| `0001652044-26-000071` | 2026-07-23 | `1:63` | `benchmark_window_unavailable` |
| `0001652044-26-000071` | 2026-07-23 | `1:126` | `benchmark_window_unavailable` |

The frozen SPY cache ends at **2026-09-04**. All three issue rows have an empty missing-component-symbol set, so this is **right-censoring / not-yet-realized outcome data**, not a historical symbology failure and not evidence that GOOG or GOOGL is absent.

The amended workflow artifact is `9995782614` (`flagship-risk-churn-acceleration-34055143306`), size **1,003,319 bytes**, digest `sha256:69a112a6c5e3584ac1b77f082624c148a49b900109f18e4469b61d27bed6e3b5`, created `2026-09-06T19:35:28Z`, with configured Actions expiry `2026-12-05T19:31:13Z`. Its market-cache manifest ID is `8fa0964c9fbf2c1adc2565fa878295a5d669b3612b95f7c700de90c9134b687e` across **508** entries. Do not conflate this study artifact with the separately archived HU-5 identity-closure evidence described above.

This amended run contains **no alpha evidence either for or against the signal**. It is neither `REJECT` nor `PROMOTE`. No methodology change is justified by observing this censoring state.

The next legitimate canonical rerun is blocked on observability, not design work: refresh the frozen-contract market cache only after every predeclared endpoint exists, rerun the unchanged cache/symbology preflight, and then execute the unchanged amended study once. The latest blocking `1:126` endpoint is expected around **2027-01-22** under the exchange calendar, but the actual gate is the endpoint's presence in the refreshed benchmark/component cache, not the calendar estimate. Full frozen record: [`../research/historical-universe/flagship-amended-rerun-2026-09-06.md`](../research/historical-universe/flagship-amended-rerun-2026-09-06.md).

## Current interpretation

The durable flagship state is therefore:

- the unchanged post-closure run remains **`INSUFFICIENT` due `ambiguous_security_mapping`** under its original methodology;
- the separately amended multi-class run remains **`INSUFFICIENT` due right-censored multi-class outcome horizons**;
- neither result is signal rejection or promotion;
- the next flagship action is to wait for the frozen horizons to become observable, not to tune the methodology around the insufficiency.

## Evaluation discipline going forward

Future promotable claims must retain exact PIT feature and outcome lineage, predeclared horizons and split logic, purging of unrealized development outcomes, multiple-testing-aware gates, explicit transaction-cost assumptions, robustness diagnostics, immutable code/config/data identity, and an honest terminal state of `PROMOTE`, `REJECT`, or `INSUFFICIENT`.

The published retrieval and Cross-Sectional holdouts are historical benchmarks. Any new claim of untouched holdout performance requires a newly sealed, access-controlled holdout under the lifecycle defined in [`holdout_policy.md`](holdout_policy.md).
