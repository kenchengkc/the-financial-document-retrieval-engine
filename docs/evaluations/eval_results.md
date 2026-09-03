# Evaluation Results

This is the canonical active record of FDRE measurements. Methodology and freeze rules live in [`eval_plan.md`](eval_plan.md). Historical one-off diagnostics live under `docs/archive/`.

Unless otherwise stated, measurements use the production corpus/provider environment available at the recorded run date. Historical results remain preserved; they are not silently rewritten when later runs improve or diagnose them.

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

The current constituent seed is a current-constituent snapshot and is therefore **not** a historical survivorship-free universe. Historical Universe v1 is addressing that limitation.

## Production Cross-Sectional v2 development replay

The frozen 28-case Cross-Sectional v2 development suite has been executed through the deployed `POST /research/screen` HTTPS path.

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

This is the preferred current production-screen headline because it measures the real deployed path rather than the earlier executor-only/deployment-parity probes.

## Cross-Sectional v2 sealed holdout — immutable first reveal

The 14-case sealed holdout was first executed on **2026-08-26** after construction without screen/retrieval execution. The first-run artifact remains frozen at:

```text
data/evals/results/cross-sectional-v2-holdout-first-run/
```

| Metric | First holdout result |
| --- | ---: |
| Issuer Recall@1 | **1.000 (14/14)** |
| Issuer Recall@3 / @5 | **1.000 / 1.000** |
| Exact evidence Recall@1 / @3 / @5 | **0.778 / 0.778 / 0.778** |
| Strict condition grounding | **0.0% (0/8)** |
| PIT leakage | **0%** |
| p50 / p95 latency | **3.15 s / 6.15 s** |
| Max semantic calls | **1** |

The frozen `0/8` strict score is not an issuer-ranking failure. Post-freeze diagnosis showed the selected accessions, structured values, source-accession chains, and pass/fail decisions were correct; the mismatch was in snapshot-scoped lineage IDs caused by different panel snapshot context. The frozen result remains unchanged. See `docs/archive/cross_sectional_condition_replay.md` for the historical diagnosis.

## Retrieval benchmark

The reviewed retrieval contract contains 120 questions (80 development / 40 holdout).

### Holdout retrieval

| Variant | Recall@10 | MRR | Table Recall@10 |
| --- | ---: | ---: | ---: |
| Dense only | 0.350 | 0.192 | 0.500 |
| Sparse only | 0.250 | 0.068 | 0.000 |
| **Hybrid** | **0.375** | **0.164** | **0.500** |

Hybrid Recall@10 improved from the first freeze but remains below the aspirational **0.85** gate. Do not present the current holdout as production-ready semantic coverage; stronger human-authored paraphrase coverage is still required.

### Content-grounded ablation continuity

| Variant | Recall@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: |
| Baseline | 0.152 | 0.086 | 0.102 |
| **Shipped multi-query** | **0.212** | **0.134** | **0.153** |
| + neighbor expansion | **0.242** | — | — |

Multi-query expansion remains the shipped default because it produced a measured ~40% Recall@5 lift on the grounded ablation.

### Exact versus ANN

| Metric | Result |
| --- | ---: |
| ANN Recall@10 | **1.00** |
| Max delta from exact | **0.00** |

The measured filtered-search ranking showed no observed top-10 degradation from the HNSW ANN path under the benchmark configuration.

## Storage optimization

Migrating embeddings from full precision to PostgreSQL `halfvec` reduced the database from approximately **15 GB to 11 GB (~27%)**. Exact before/after top-10 ANN comparisons showed no observed ranking change under the benchmark.

This is the architectural precedent for Historical Universe: grow research history in the cheapest representation that preserves the research contract rather than multiplying expensive vector storage by default.

## Cached answer path

Verified point-in-time-aware answer-cache hits are approximately **44 ms** in the documented production measurement. Abstentions are not cached.

## Flagship risk-churn acceleration study

The flagship study is a precommitted expanding walk-forward experiment. Workflow success means the study executed and artifacts verified; it does **not** imply a statistically promotable signal.

### Latest successful run state

Latest documented post-hardening run:

- selected tickers: **171**;
- scored events: **1,214**;
- eligible walk-forward folds: **1**;
- OOS observations: **60**;
- primary `1:63` realized observations: **0**;
- explicit primary result: **`INSUFFICIENT_NOT_YET_REALIZED`**;
- secondary `1:21` IC mean: **0.11433335897634628**;
- secondary `1:21` long/short mean: **0.016741147871689704**;
- quantile monotonicity: **0.3**;
- stability-ready: **false**;
- statistical status: **insufficient**;
- implementation status: **not statistically eligible**;
- promotion status: **insufficient**;
- live-trading-ready: **false**.

The 1:21 diagnostic is directionally positive but statistically inadequate. The primary 1:63 horizon had not yet realized for the sealed OOS events at evaluation time.

More importantly, the current study has only one eligible fold while the statistical gate requires at least four independent IC folds. Waiting for the current July 2026 events to realize is therefore **not sufficient by itself**; FDRE needs longer historical research depth and a credible historical universe.

### Runtime/failure-engineering result

After session-lifecycle, market-provider retry/circuit-breaker, and explicit-primary-status fixes, a warm-cache run completed successfully without the earlier idle-in-transaction failure or coverage retry loop. Treat that run as steady-state cache/lifecycle validation, not a cold-cache speedup claim.

## Historical Universe v1 evaluation state

**HU-1 is complete.** The repository now has:

- stable listed-security identity beneath issuer/CIK;
- time-varying symbol/name/exchange periods;
- time-varying universe memberships;
- source provenance, confidence, and verified/provisional/rejected state;
- deterministic PIT snapshot hashing;
- fail-closed interval/identity behavior;
- migration and unit coverage.

### First production-backed HU-2 coverage audit

The read-only audit completed successfully on 2026-08-30 ([Actions run
`33293629439`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33293629439)).
It replayed two pinned public change sources plus a content-hashed SEC CIK lookup and produced
audit ID `51149298c38040e01bc393f47eb96c48ad868cd65d55230a64a23107bf36f54b`.

| Measurement | Result |
| --- | ---: |
| Date coverage | 1976-07-01 through 2026-08-18 |
| Normalized evidence observations | 1,730 |
| `shawnlinxl/snp-history` observations | 970 |
| Wikipedia historical-component observations | 760 |
| Production issuer/company rows | 499 |
| Stable securities / historical identity periods | 0 / 0 |
| Exact SEC issuer-name resolution | 545 |
| No exact SEC historical-name match | 1,106 |
| Exact name mapping to multiple CIKs | 79 |
| Resolved security observations | 0 |
| Verified/provisional/conflicting events | 0 / 0 / 0 |
| Materialized/promoted membership intervals | 0 / 0 |

This is a useful fail-closed result, not historical-universe coverage. HU-1 created the schema and
snapshot contract but did not seed production stable securities. Consequently, **545 observations
covering 437 unique CIKs resolve to an SEC issuer and then stop at the missing security layer**.
The remaining work queues contain **1,106 observations / 868 normalized names** with no exact SEC
name match and **79 observations / 62 normalized names** with dated CIK ambiguity.

For the intended 2010+ research window, the audit has 1,055 observations: 291 resolve to an issuer,
735 have no exact issuer-name match, and 29 are issuer-ambiguous. The stable-security resolution
rate is therefore **0.0%**, versus the newly precommitted HU-2 pipeline-readiness floor of **95%**.

Before identity resolution, the sources contain 241 exact cross-source event keys covering 482
observations. Five same-date/same-symbol keys contain both additions and removals (`AET`, `GAS`,
`JCI`, `FOX`, and `FOXA`). These are queued for corporate-action review; they are not automatically
called source conflicts. No reconciled conflict count is yet meaningful because no observation
resolved to a stable security.

The committed present-day seed describes 503 constituent symbols, maps 502 through the issuer
catalog, and leaves `CBOE` unmapped. It collapses those symbols to 499 issuer-ingestion tickers; it
is not a stable listed-security master and must not be backdated. The ordered remediation is:

1. complete the current constituent catalog and create evidenced present-day security identities,
   preserving all share classes and creating no historical membership;
2. add source-backed historical issuer aliases and dated CIK-successor adjudications;
3. classify the five same-symbol corporate-action keys and retain genuine disagreements;
4. add an independently sourced complete constituent anchor at or before 2010; and
5. rerun until the gate in [`historical_universe_v1.md`](historical_universe_v1.md) passes.

No historical S&P membership performance/result was claimed at this initial checkpoint. It is
retained as provenance and superseded by the production-promotion measurement below.

### HU-2 production promotion — complete

The canonical explicit apply completed in [Actions run
`33462343599`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33462343599)
at commit `4958bf6e464563d0e72e958faa16603667a32df4`. The final
`fdre-hu2-final-promotion-gate-v4` artifact reports `promotion_gate_met: true`.

| Production measurement | Result |
| --- | ---: |
| Identity-safe anchor | **500** securities at 2009-12-30 |
| Historical-only / current issuer creates | **396 / 6** |
| Common-stock security creates | **483** |
| Identity / membership periods created | **1,004 / 1,004** |
| Verified / provisional memberships | **809 / 195** |
| 2010+ identity resolution | **1,044 / 1,055 (98.96%)** |
| Published residual identity queue | **11 unresolved** |
| Post-anchor boundary decisions | **299 verified / 66 provisional** |
| Identity overlaps / membership overlaps | **0 / 0** |
| Memberships missing identity coverage | **0** |

Both the strict and provisional snapshots match anchor ID
`cf6022bafa00f007712089f80a9225df6b87284e400fd4fac0c81f2e71c5351f` at exactly 500
constituents. Provisional replay reproduces snapshot ID
`ca9f9b06aafeb2bbe9cfd75a3792256469d4824fe116830c6ee724ea1ca1da56`; the strict snapshot ID is
`168bc0b972c8781f02d67d974522880233f32b38e2557c45d7f8b37e51805d7e`.

The apply also closed the current CBOE catalog/identity gap. During live validation, the pinned
component source's XOM row was found to reference ExxonMobil Holdings Corp (CIK `0002115436`)
rather than the listed Exxon Mobil Corp issuer. The exact `(XOM, 0002115436)` source claim is now
canonically corrected to SEC CIK `0000034088`, recorded in the reconciliation artifact, and guarded
by a dry-run ticker-owner collision check.

HU-2 completion does not promote uncertain evidence. All 11 residual observations remain in the
immutable provisional queue, and the 66 unresolved post-anchor membership boundaries remain
provisional. Strict research snapshots continue to reject any date/security affected by active
provisional evidence.

### HU-2 remediation checkpoint — R0 security bootstrap and R1 issuer aliases

The first two remediation steps were measured in production on 2026-08-30 without backdating the
current constituent seed or writing historical memberships.

`HU2-R0` was explicitly applied in [Actions run
`33299892680`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33299892680).
It created **502 stable common-stock securities and 502 provisional current identity periods** for
the 502 mapped present-day constituent symbols. Those identities begin on the committed current
snapshot date, **2026-06-08**. They do not assert when the securities entered the S&P 500 and do not
establish pre-snapshot ticker history. `CBOE` remains the one unmapped current symbol.

Immediately after R0, the 2010+ audit resolved **98 / 1,055 observations (9.29%)** to stable
securities. This established that the present-day security master removes the zero-security
bootstrap bottleneck but does not by itself provide historical identity coverage.

`HU2-R1` then added an evidence-scoped cross-source issuer-alias derivation and was measured by
[Actions run
`33300609711`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33300609711),
producing audit ID `d3405d7c325a36f5f292fa615dc1411ca2322a070130d1f8e11fbc801296e4a5`.
An alias is usable only for the exact membership-evidence row supported by independent sources on
the same universe/date/event-type/symbol key, where another source's issuer name resolves uniquely
through the pinned SEC cumulative CIK lookup. Derived aliases are not global name-to-CIK rules,
are not chained transitively, and conflicting CIK derivations fail closed.

| Measurement | Post-R0 | Post-R1 |
| --- | ---: | ---: |
| Stable securities / current identity periods | 502 / 502 | 502 / 502 |
| Stable-security CIKs | 499 | 499 |
| Full-history issuer names resolved | 545 | **702** |
| Full-history issuer names unresolved | 1,101 | **944** |
| Full-history security observations resolved | 143 | **198** |
| 2010+ security observations resolved | 98 / 1,055 | **147 / 1,055** |
| 2010+ stable-security resolution rate | 9.29% | **13.93%** |
| Derived issuer-alias evidence rows | — | **157** |
| Distinct derived normalized alias names | — | **153** |
| Verified / provisional reconciled events | 1 / 140 | **56 / 85** |
| Reconciled events carrying conflict codes | 3 | **58** |

R1 therefore added **49 resolved observations in the 2010+ target window**, a **+4.64 percentage
point** improvement. Across the full evidence history it created 157 source-backed alias
observations; 55 of those reach a stable security, while **102 now stop at the next fail-closed
boundary: the issuer resolves, but FDRE has no stable historical common-stock security for that
CIK**.

The post-R1 remediation audit contains **509 evidence rows across 313 resolved CIKs** that are
blocked by the missing historical stable-security layer. It also retains **944 rows / 769 normalized
names** without exact SEC or cross-source alias resolution and **79 rows / 62 normalized names**
with exact-name CIK ambiguity. The 2010+ resolution rate remains far below the **95%** pipeline-
readiness floor, so the HU-2 promotion gate remains closed.

The increase from 3 to 58 reconciled conflict-bearing events is not treated as evidence that R1
manufactured disagreement. Reconciliation checks opposing add/remove events by **stable security +
effective date**, whereas the earlier raw diagnostic only counted same-symbol opposing rows. Better
identity resolution therefore exposes additional same-security corporate-action/ticker-transition
boundaries that were previously invisible. Those boundaries remain provisional and require dated
adjudication; they are not guessed away.

The highest-leverage next remediation is now historical stable-security/identity expansion for the
already-resolved issuer queue, while preserving share-class distinctions and dated corporate-action
lineage. Creating one historical security per CIK without listed-security evidence would violate the
HU fail-closed contract and is explicitly out of scope.

### HU-2 exact-lineage and component-history checkpoint

The latest successful read-only audit on `main` is [Actions run
`33330177836`](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33330177836).
It preserves the post-R1 production state while measuring two additional pinned identity sources
and a complete historical anchor. These are projected recoveries; the workflow did not write
historical membership or promote HU-2.

| Measurement | Exact ticker lineage | Historical component CIK |
| --- | ---: | ---: |
| 2010+ target observations | 1,055 | 1,055 |
| Post-R1 baseline resolved | 147 | 147 |
| Additional projected recoveries | 261 | **896** |
| Projected resolved observations | 408 | **1,043** |
| Projected resolution rate | 38.67% | **98.86%** |
| Residual observations | 647 | **12** |
| Projected unique CIKs | 193 | **539** |

The pinned fja05680 anchor contains **501 lineage tokens at 2009-12-30** and replays from source
ref `c31ac3cc56f28cf9a02b4e694eff7ceab596a0ff`. It is now explicitly classified as a
terminal-lineage/count source, not an exact point-in-time ticker source. The independent primary
check is IVV's 500-common-stock schedule as of 2009-12-31 in SEC N-Q accession
`0001193125-10-044578`. The component-history residual is 11 unresolved observations plus one
ambiguous observation. The existing production audit remains at **147 / 1,055 (13.93%)** until
the projected identities are safely materialized and re-audited.

Crossing the 95% identity-resolution floor did not by itself pass HU-2. This pre-apply checkpoint
remained gated until the later production run verified the written state, anchor alignment,
interval integrity, deterministic replay, and published unresolved queue. Those checks have now
passed in the production-promotion result above.

### HU-2 anchor reconciliation and boundary adjudication

The pinned lawcal component history at
`ed4cf46e5ec5bb02e709aa08ee8a3a218d1b7d19`, fja05680 lineage/anchor source at
`c31ac3cc56f28cf9a02b4e694eff7ceab596a0ff`, and the 501-lineage anchor effective
2009-12-30 were replayed against an empty schema before production apply.

The earlier rehearsal is retained as a regression fixture: ignoring lawcal's `created_at` rule
reproduces exactly **533** staged names, **29** missing anchor symbols, and **61** unexpected
symbols. That comparison was not a valid PIT replay. Enforcing the upstream rule removes 50
back-projected later ticker rows and leaves 483 source-valid rows.

| Anchor reconciliation | Result |
| --- | ---: |
| Original staged constituents | 533 |
| Original missing / unexpected | 29 / 61 |
| Source-valid constituents (`as_of >= created_at`) | 483 |
| Source-valid missing / unexpected vs fja | 54 / 36 |
| Historical ticker -> fja terminal-symbol aliases | 35 |
| SEC-confirmed lawcal membership gaps | 18 |
| Rejected lawcal false positive | 1 (`ASH`) |
| Rejected duplicate fja display lineage | 1 (`XL`) |
| Adjudicated constituents | **500** |
| SEC IVV common-stock holdings | **500** |

All 54/36 residual symbol differences are classified. The arithmetic is exact:
`483 - ASH + 18 SEC-confirmed gaps = 500`. The 35 ticker pairs explain differences without being
written as historical identities. The 18 gaps are APH, ARG, BKNG, CB, CLF, D, FCX, FOXA, GAS,
GOOGL, HUM, JCI, LDOS, MJN, ROST, SRE, TROW, and V. IVV's filed security names confirm their
membership, but the filing does not contain ticker/CIK identity, so these rows remain blocked from
production until dated identity evidence is attached.

Every one of the 999 lawcal intervals now also has separate start/end evidence decisions. An exact
lawcal date needs one exact external match; a lawcal date marked approximate needs two. A verified
membership interval still remains identity-provisional when `created_at > date_added`.

| Boundary adjudication | All intervals | Starts in 2010+ |
| --- | ---: | ---: |
| Source intervals audited | 999 | 365 |
| Both membership boundaries corroborated | 441 | 299 |
| Strict materializable verified intervals | **181** | **170** |
| Boundary provisional, identity valid | 277 | 38 |
| Boundary verified, identity provisional | 260 | 129 |
| Boundary and identity provisional | 281 | 28 |

The corrected dry-run materialization plan therefore reports 181 verified and 818 provisional
memberships, including 541 whose point-in-time symbol validity begins after the reported
membership start. It continues to perform no writes.

### Prior fail-closed rehearsal retained for provenance

| Staged measurement | Result |
| --- | ---: |
| Historical issuer creates (`ticker = NULL`) | 394 |
| Current issuer creates | 500 |
| Stable security creates | 980 |
| Gap-preserving identity periods | 999 |
| Membership intervals | 999 |
| Independently verified memberships | 411 |
| Provisional memberships | 588 |
| Provisional anchor-date constituents | 533 |
| Expected anchor-date constituents | 501 |
| Missing expected anchor symbols | 29 |
| Unexpected staged anchor symbols | 61 |
| Identity overlaps | 0 |
| Membership overlaps | 0 |
| Memberships missing identity coverage | 0 |

That provisional snapshot replayed to the same snapshot ID, but it did not match the anchor. Strict
resolution failed closed on active provisional membership. The explicit apply therefore exited
non-zero, reported `applied: false`, and rolled back all staged companies, securities, identities,
and memberships; post-attempt row counts were zero in all four tables.

This fail-closed rehearsal is retained as provenance. It was superseded by the identity-safe
500-security anchor, dated decisions for all 18 SEC-confirmed gaps, independent identity evidence
for the formerly deferred ticker rows, the 11-row residual queue, and the successful production
promotion reported above. The 66 unresolved post-anchor membership boundaries remain provisional;
they were retained rather than guessed.

## Historical measurements retained for provenance

Earlier snapshots/results remain useful for showing improvement over time but are no longer the current headline:

- Cross-Sectional v1 development baseline: issuer Recall@1 **0.667**, Recall@3/5 **0.833/0.833**, zero PIT leakage; inherited evidence labels were largely ineligible for its exact latest-filing screen contract.
- Earlier single-name/cross-sectional retrieval latency gates measured approximately **1.95 s / 1.74 s p95** under the then-current benchmark harness.
- The archived latency diagnostic records the panel-feature-pruning optimization that removed unnecessary panel construction before the deployed route was available.

## Reproduce core evaluations

```bash
export FDRE_ALLOW_PROD=1
export PYTHONPATH=src:.

python3 -m scripts.benchmarks.benchmark_latency --k 10 --warmup 2 --repeats 2
python3 -m scripts.benchmarks.benchmark_ann_recall --k 10
python3 -m scripts.pipelines.retrieval_pipeline eval data/evals/retrieval_benchmark.jsonl \
  --require-reviewed --split holdout --k 10
```

Signal and Historical Universe workflows should additionally preserve their immutable config/data/code/universe identities when reporting results.
