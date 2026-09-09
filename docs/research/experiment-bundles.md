# Portable experiment bundles

FDRE can export a registered research experiment as a deterministic JSON bundle that is verifiable without a live database, model provider, SEC request, or market-data refetch.

A bundle contains:

- the immutable research root manifest;
- the exact persisted walk-forward study;
- OOS diagnostics;
- multiple-testing-aware selection output;
- implementation/cost analysis;
- the terminal promotion report;
- each child artifact's expected experiment type and SHA-256 digest;
- a SHA-256 identity for the bundle itself.

The bundle intentionally contains no generation timestamp, so exporting the same registered root twice produces the same bytes after canonical JSON serialization and the same `bundle_sha256`.

## Export

From a database containing the registered experiment chain:

```bash
python -m scripts.research.research_experiment bundle \
  <experiment-id> \
  --output research-bundle.json
```

The API exposes the same verified payload at:

```text
GET /research/experiments/{experiment_id}/bundle
```

Bundle construction first verifies the persisted root and every referenced child payload. A corrupted registry row is therefore rejected rather than exported.

## Verify offline

A reviewer can verify the resulting file without database access:

```bash
python -m scripts.research.research_experiment verify-bundle \
  research-bundle.json \
  --expected-experiment-id <git-pinned-experiment-id>
```

Verification fails closed unless all of the following hold:

1. The bundle SHA-256 matches its contents.
2. The bundle root matches the independently supplied expected experiment id, when provided.
3. The manifest's content-addressed experiment id recomputes exactly.
4. Every child reference, experiment type, and payload SHA-256 matches the manifest.
5. Every child payload validates against its typed research-report schema.
6. The persisted OOS promotion report replays to exactly the terminal decisions recorded in the root manifest.

The `--expected-experiment-id` check matters. A self-consistent bundle proves internal integrity; comparing it with a root id pinned in Git, a paper, or an evaluation record also protects against wholesale substitution of a different self-consistent experiment.

## What this proves—and what it does not

A verified bundle proves that a published research claim is tied to one exact code/data/universe identity and one exact persisted chain of research outputs. It also proves that the terminal decision is reproducible from those persisted artifacts.

It does **not** independently redownload source filings or market data, rerun feature engineering from raw inputs, or establish that a research result is profitable. Full source-level reproduction still depends on the dataset, market-data, universe, and feature snapshot identities recorded in the manifest.

Portable bundles are intended as a compact audit/review surface, not as a replacement for the underlying point-in-time data pipeline or sealed holdout process.
