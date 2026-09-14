# Portable experiment bundles

FDRE can export a registered research experiment as a deterministic JSON bundle that is verifiable without a live database, model provider, SEC request, or market-data refetch.

A bundle contains:

- the immutable research root manifest;
- the replay inputs required by that registry version;
- the exact persisted walk-forward study;
- OOS diagnostics;
- multiple-testing-aware selection output;
- implementation/cost analysis;
- the terminal promotion report;
- each child artifact's expected experiment type and SHA-256 digest;
- a SHA-256 identity for the bundle itself.

For registry v5, the replay chain starts from the persisted SEC-derived panel source: scoped company identity, filing metadata, comparable-filing candidates, and parsed Risk Factors elements. It independently rebuilds PIT panel rows before replaying feature construction, walk-forward evaluation, diagnostics, selection, implementation, and promotion.

The bundle intentionally contains no generation timestamp, so exporting the same registered root twice produces the same bytes under the documented canonical JSON serialization and the same `bundle_sha256`.

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
6. The replay inputs regenerate every computational layer supported by that registry version.
7. The computationally replayed terminal decisions exactly match the root manifest.

Schema validation is deliberately strict: an older or hand-built payload that is internally hash-consistent but omits fields required by the current typed research contract is rejected rather than treated as reproducible evidence.

The `--expected-experiment-id` check matters. A self-consistent bundle proves internal integrity; comparing it with a root id pinned in Git, a paper, or an evaluation record also protects against wholesale substitution of a different self-consistent experiment.

## Raw SEC bytes are a separate input artifact

Registry v5 begins from the persisted SEC-derived corpus. It does not pretend that legacy historical raw filing files exist when they were not retained.

New SEC parses additionally record exact-byte/parser provenance, and retained source files can be exported as a deterministic raw replay ZIP. That bundle can re-run `HtmlFilingParser` from the exact bytes without SEC or database access. See `docs/research/sec-source-replay.md`.

A legacy document without retained original bytes or parse provenance remains panel-source reproducible but is **not** described as raw-byte reproducible. FDRE does not manufacture historical provenance by redownloading a filing later.

## What this proves—and what it does not

A verified research bundle proves that a published research claim is tied to one exact registered experiment root and that every computational layer represented by that registry version reproduces its persisted outputs. A separately verified SEC raw replay bundle proves the stronger upstream statement for the documents it contains: the recorded parser version reproduces the persisted element identity from exact retained filing bytes.

Neither artifact establishes that a signal is profitable, upgrades historical/public holdouts into unseen data, or relaxes the project's point-in-time, abstention, robustness, or promotion gates.

Portable bundles are audit/review surfaces, not replacements for the underlying point-in-time data pipeline or sealed holdout process.
