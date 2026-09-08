# Benchmark Holdout Lifecycle

FDRE distinguishes benchmark **provenance** from benchmark **current visibility**. A dataset can have been a valid sealed holdout at its first permitted evaluation and later become public for reproducibility. Once revealed, it must not be presented as an unseen holdout for future tuning claims.

## Lifecycle states

### Development

Development cases are visible to implementers and may be used to diagnose failures, choose retrieval variants, tune thresholds, and improve system behavior. Results on development cases are useful engineering measurements but are never described as untouched holdout performance.

### Sealed holdout

A sealed holdout is access-controlled and unavailable to the implementation/tuning loop before its first permitted evaluation.

While sealed:

- inputs are not committed to the public repository;
- implementers do not inspect labels or per-case outcomes;
- the evaluation runs against a pinned code revision, corpus/data snapshot, configuration, and benchmark hash;
- the first-run outputs are persisted immutably with enough identity to reproduce the evaluation context;
- a disappointing result is preserved and diagnosed rather than relabeled or replaced.

### Published historical benchmark

After the first permitted evaluation, a holdout and its immutable first-run result may be published to support reproducibility and external review. Publication changes its **visibility state**, not its historical provenance.

After reveal:

- the benchmark may be used for regression checks, diagnostics, and historical comparison;
- its original first-run result remains the canonical untouched-holdout result for the revision evaluated at first reveal;
- subsequent results must be described as reruns or regression measurements, not new unseen-holdout performance;
- tuning against the revealed cases disqualifies them from future holdout claims;
- a new unseen-performance claim requires a newly constructed sealed, access-controlled holdout.

## Existing published holdouts

The checked-in retrieval holdout split and Cross-Sectional v2 holdout are **published historical benchmarks** today. Their paths, manifests, hashes, and first-run artifacts remain in the repository because they provide useful provenance.

For Cross-Sectional v2, the manifest fields such as `status: sealed`, `sealed_at`, and `evaluation_status: first_run_frozen` describe the benchmark's state and provenance at construction/first execution. They are intentionally not rewritten after publication, because mutating a frozen manifest would damage the audit trail.

The immutable Cross-Sectional v2 first-run artifact remains under:

```text
data/evals/results/cross-sectional-v2-holdout-first-run/
```

The public dataset remains under:

```text
data/evals/cross_sectional_benchmark.v2.holdout.jsonl
```

Neither should be treated as an unseen future holdout.

## Rules for future holdouts

For any new retrieval, research-screen, or signal-research holdout intended to support an unseen-performance claim:

1. Construct and hash the dataset without evaluating the implementation being tested.
2. Keep labels and cases outside the public repository and normal development surface until the permitted evaluation.
3. Predeclare the evaluation contract, primary metrics, and promotion/failure criteria before reveal.
4. Pin code, data/corpus identity, configuration, and provider/model identity where applicable.
5. Persist the first permitted run and its per-case outputs immutably.
6. Publish the benchmark only after that first run if reproducibility benefits justify reveal.
7. Reclassify the revealed benchmark as a published historical benchmark and rotate a new sealed holdout for the next untouched claim.

This lifecycle preserves both goals FDRE cares about: credible unseen evaluation at decision time and transparent reproducibility after the fact.
