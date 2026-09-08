# Evaluation Methodology and Benchmark Contracts

This document defines **how FDRE evaluations are constructed, frozen, executed, and interpreted**. Current measured results live in [`eval_results.md`](eval_results.md). The benchmark visibility lifecycle is defined in [`holdout_policy.md`](holdout_policy.md). Historical one-off diagnostics live under `docs/archive/`.

## Evaluation principles

FDRE evaluation follows five rules:

1. **Point-in-time correctness is mandatory.** Future filings, facts, universe membership, or market outcomes invalidate a result regardless of retrieval quality.
2. **Reviewed benchmark inputs are immutable after reveal.** A bad result is diagnosed, not relabeled away.
3. **Development and holdout claims are separated.** Generated/development cases are never reported as untouched holdout performance. Once a holdout is revealed publicly, it becomes a published historical benchmark and cannot support a new unseen-holdout claim.
4. **Structured correctness and semantic retrieval are scored separately.** A correct issuer ranking does not hide wrong values, wrong lineage, or unsupported evidence.
5. **Infrastructure success is not research success.** Signal workflows may complete successfully while the statistical result remains `REJECT` or `INSUFFICIENT`.

## Retrieval benchmark

The canonical reviewed retrieval dataset is:

```text
data/evals/retrieval_benchmark.jsonl
```

Contract:

- 120 human-reviewed questions;
- 80 development / 40 historical holdout cases;
- narrative, table, legal, guidance, temporal, cross-sectional, filter, and abstention categories;
- reviewer identity and explicit abstention labels;
- stable evidence labels based on accession, section, normalized quotation, and content fingerprint.

The checked-in 40-case holdout split is now public and therefore serves as a **published historical benchmark**. Its original first-reveal measurement remains valid historical provenance, but future runs are regression/rerun measurements rather than new unseen-holdout results. Any future untouched retrieval claim requires a newly sealed, access-controlled holdout under [`holdout_policy.md`](holdout_policy.md).

Example historical-holdout replay:

```bash
FDRE_ALLOW_PROD=1 python3 -m scripts.pipelines.retrieval_pipeline eval \
  data/evals/retrieval_benchmark.jsonl \
  --require-reviewed --split holdout --k 10
```

### Retrieval metrics

Primary metrics:

- Recall@K;
- MRR;
- nDCG@K where applicable;
- table-specific Recall@K;
- abstention quality;
- entity-resolution accuracy;
- latency;
- exact-vs-ANN ranking agreement.

The aspirational retrieval Recall@10 gate remains **0.85**. Current status is recorded only in `eval_results.md` so the metric does not drift across documents.

## Cross-Sectional v2 benchmark

The immutable v1 benchmark remains historical provenance. Cross-Sectional v2 is the canonical current research-screen evaluation contract.

### Development freeze

Canonical file:

```text
data/evals/cross_sectional_benchmark.v2.development.jsonl
```

It contains 28 reviewed cases across:

| Task type | Count |
| --- | ---: |
| semantic screen | 10 |
| temporal screen | 3 |
| structured screen | 5 |
| change screen | 5 |
| semantic + structured | 5 |

The freeze manifest pins file hashes, component hashes, case counts, task distribution, and holdout status. CI fails if the materialized development benchmark drifts from reviewed components.

### Evidence-label eligibility

A v2 evidence label is valid only when:

1. the gold issuer is resolved inside the frozen case universe;
2. the exact filing is selected PIT using the case `as_of`, form, and amendment policy;
3. `metadata.selected_accession` identifies that exact filing;
4. reviewed evidence is a substring of a stored chunk from that accession and gold issuer;
5. the case stores direct evidence rather than hydrating an older retrieval-question label.

Candidate-ranking tools may help reviewer triage but never generate gold labels automatically.

### Published historical holdout

Canonical public file:

```text
data/evals/cross_sectional_benchmark.v2.holdout.jsonl
```

The 14-case Cross-Sectional v2 holdout was constructed using PIT panel/source data without executing the screen or semantic retrieval, then sealed before its first permitted execution. Its first permitted execution is frozen under:

```text
data/evals/results/cross-sectional-v2-holdout-first-run/
```

That first-run artifact is immutable and preserves the valid untouched-holdout result for the pinned first-evaluation revision. The inputs have since been revealed in this public repository, so the dataset is now a **published historical benchmark**. Future reruns may diagnose changes but may not overwrite the first-run artifact or be described as fresh unseen-holdout performance.

The holdout manifest is also intentionally immutable. Historical fields such as `status: sealed`, `sealed_at`, and `evaluation_status: first_run_frozen` record the benchmark's lifecycle state at construction and first execution; they are not retroactively rewritten after publication. See [`holdout_policy.md`](holdout_policy.md) for the lifecycle contract that governs future holdouts.

### Cross-sectional metrics

Reports distinguish:

- issuer Recall@1 / @3 / @5;
- exact evidence Recall@1 / @3 / @5;
- condition correctness/source grounding;
- exact snapshot-scoped lineage replay;
- strict condition grounding = correctness + exact lineage replay;
- PIT leakage;
- semantic-call count;
- executor/API/end-to-end latency as explicitly labeled.

This separation exists because the frozen first holdout revealed a lineage-context mismatch despite correct structured values/accessions. The historical diagnosis is preserved in `docs/archive/cross_sectional_condition_replay.md`; the durable scoring contract is encoded here and in `feature_lineage.md`.

## Production screen evaluation

Development cases may also be replayed through the deployed `POST /research/screen` route to measure the real production path. These runs must record enough context to distinguish:

- panel construction / PIT filing selection;
- embedding provider time;
- sparse/dense retrieval;
- fusion/reranking;
- evidence hydration;
- response construction;
- HTTP/proxy overhead.

Quality gates must be rechecked after any latency optimization that changes retrieval behavior.

## Signal-study evaluation contract

FDRE signal research should behave like a falsifiable experiment, not a chart generator.

Minimum contract for promotable studies:

- exact PIT event timestamp and selected feature lineage;
- predeclared primary/secondary horizons;
- train / validation / sealed OOS walk-forward splits;
- purging of unrealized development outcomes;
- cross-sectional Spearman IC and stability diagnostics;
- quantile/long-short summaries;
- clustered/bootstrap inference where supported;
- multiple-testing-aware promotion rules;
- turnover and explicit transaction-cost assumptions;
- sector/temporal robustness;
- immutable experiment/config/data/code identity;
- valid outcomes of `PROMOTE`, `REJECT`, or `INSUFFICIENT`.

### Flagship risk-churn acceleration

The flagship methodology is precommitted. It uses:

- risk-churn acceleration as the feature;
- primary horizon `1:63`;
- secondary horizons `1:21` and `1:126`;
- expanding 24-month train / 6-month validation / 6-month test windows with 6-month step;
- purged unrealized outcomes;
- sealed-OOS multiple-testing gates;
- monthly long/short implementation diagnostics at 5/10/25/50 bp;
- sector robustness, concentration, and decay checks;
- immutable artifact verification.

Do not alter the methodology after observing results simply to manufacture promotion.

## Historical Universe evaluation

Historical Universe introduces a new correctness dimension: **universe eligibility itself**.

HU tests must include:

- future constituent additions cannot appear before `effective_from`;
- removals disappear at the half-open boundary;
- historical ticker changes resolve to the correct stable security;
- simultaneous share classes remain distinct;
- provisional/rejected evidence behaves fail-closed in strict mode;
- snapshot hashes change when provenance changes;
- source disagreements are surfaced in audit output;
- current constituent snapshots are never treated as proof of past membership.

HU-2 must produce coverage/audit metrics before HU-derived historical universes are used in flagship research.

## Reporting rules

- Put **current measurements** in `eval_results.md`.
- Put **methodology/contracts** here.
- Put **holdout visibility and reveal rules** in `holdout_policy.md`.
- Put **structural invariants** in `architecture.md` / `feature_lineage.md` / `historical_universe_v1.md`.
- Put **one-off forensic investigations** in `docs/archive/`.
- Never duplicate a dated metric across several active docs unless it is a deliberate README headline.
