# Cross-Sectional v2 Condition Replay Diagnosis

> Historical diagnostic note. This document preserves the frozen Cross-Sectional v2 holdout replay investigation. Current evaluation methodology and results live in [`docs/eval_plan.md`](../eval_plan.md) and [`docs/eval_results.md`](../eval_results.md).

## Frozen first-run result

Part 7.5 remains immutable:

- issuer Recall@1: `14/14`
- exact evidence Recall@1/3/5: `0.778`
- strict condition grounding: `0/8`
- PIT leakage: `0%`
- p50/p95 latency: `3.15 s / 6.15 s`

The frozen result files remain under `data/evals/results/cross-sectional-v2-holdout-first-run/`.

## Development control

A fresh production replay of all 15 reviewed Part-7.2 condition-bearing development cases was run before touching scoring semantics.

Result:

- exact condition replay: `15/15`
- condition correctness/source grounding: `15/15`
- issuer Recall@1: `15/15`
- PIT leakage: `0%`

This ruled out a general regression in `execute_research_screen`, structured-value calculation, prior-filing selection, or the strict evaluator.

## Post-freeze holdout diagnosis

After the first holdout result was frozen, an explicit sealed-holdout diagnostic re-executed only the 8 condition-bearing cases and compared every reviewed condition field separately.

Result:

- condition correctness/source grounding: `8/8`
- exact lineage replay: `0/8`
- mismatched `current_lineage_id`: `8/8`
- mismatched `prior_lineage_id`: `2/2` change cases
- mismatched selected accession: `0/8`
- mismatched selected prior accession: `0/2`
- mismatched metric/operator/threshold/change semantics: `0/8`
- mismatched feature identity: `0/8`
- mismatched pass/fail: `0/8`
- mismatched current/prior/observed values: `0/8`
- mismatched source-accession chains: `0/8`

The official Part 7.5 strict score therefore remains correctly reported as `0/8`, but it is specifically an **exact snapshot-scoped lineage replay failure**, not a structured-screen correctness failure.

## Root cause

`FeatureLineage.lineage_id` includes `corpus_snapshot_id`. That snapshot fingerprints the complete source-document set used by a `ResearchPanel` query. It is intentionally broader than the accessions required by one feature.

The Part-7.2 development gold was captured from the production screen-context panel and still replays exactly. The Part-7.4 holdout was deliberately constructed without screen execution using a raw PIT panel review path. The raw review produced the same selected filings, feature values, prior values, and source-accession chains, but its panel snapshot context was not identical to the later five-issuer screen execution. The resulting lineage IDs therefore differ by design.

No holdout labels were edited after seeing the result, and no production lineage hash was weakened to improve the score.

## Durable lesson

Cross-sectional reports now expose three separate condition diagnostics:

1. **Condition correctness/source grounding** — selected filings, condition identity, values, pass/fail, and source-accession chain.
2. **Exact lineage replay** — current/prior snapshot-scoped lineage IDs.
3. **Strict condition grounding** — the conjunction of correctness/source grounding and exact lineage replay.

For future sealed benchmarks that score exact lineage replay, lineage labels must be captured from a raw `ResearchPanel` built with the exact frozen screen-plan universe and PIT filters.

## Reproduce the development diagnostic

```bash
FDRE_ALLOW_PROD=1 python3 -m scripts.diagnose_condition_replay \
  data/evals/cross_sectional_benchmark.v2.conditions.dev.jsonl \
  --split development
```

A sealed holdout remains protected and requires the deliberate `--allow-sealed-holdout` opt-in used by the benchmark runner.
