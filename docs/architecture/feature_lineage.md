# Point-in-Time Feature Lineage

FDRE's research-lineage contract makes structured research outputs reproducible without introducing a separate feature-store service.

This document is a stable specification. Current benchmark measurements live in [`eval_results.md`](eval_results.md).

## Contract

Every computed panel feature carries a `FeatureLineage` record containing:

- feature name;
- feature-specific calculation version;
- calculation parameters;
- exact source filing accessions;
- per-source availability timestamps;
- maximum information timestamp;
- corpus snapshot ID;
- deterministic SHA-256 lineage ID.

Changing a source filing, source timestamp, calculation version, parameter, or corpus snapshot changes the lineage ID.

## Propagation

The same lineage identity propagates through the research stack:

1. **Research panel** — each computed feature has independently verifiable lineage.
2. **Cross-sectional screen** — structured conditions reference the exact current/prior feature lineage used for the decision; the screen manifest includes a deterministic digest over structured inputs evaluated across the PIT universe.
3. **Signal study** — scored events carry selected feature lineage; complete studies expose accession-to-lineage identity, a lineage digest, and an experiment key that changes when underlying structured inputs change.
4. **Historical Universe composition** — universe snapshot identity is independent from feature lineage but should be carried alongside research dataset/experiment identity so both eligibility and information provenance can be reproduced.

Semantic-provider output is intentionally not represented as deterministic feature lineage. A structured digest fingerprints structured research inputs, not potentially nondeterministic provider/reranker output.

## Snapshot scope and benchmark replay

`FeatureLineage.lineage_id` is intentionally **panel-snapshot scoped**. The included `corpus_snapshot_id` represents the complete source-document set used by the relevant `ResearchPanel` query, not only the accessions required by one feature.

Two panel queries can therefore produce the same feature value from the same direct source accessions while producing different lineage IDs if their PIT universes/source-document sets differ.

Cross-sectional reports distinguish:

- **condition correctness/source grounding** — selected current/prior filings, metric/operator/threshold/change semantics, feature, pass/fail, values, and exact source-accession chain;
- **exact lineage replay** — equality of snapshot-scoped current/prior lineage IDs;
- **strict condition grounding** — both conditions above.

A snapshot-scoped lineage mismatch is not silently treated as a numeric/source-grounding error. Production `validate_screen_lineage(...)` still fails closed each actual condition against its actual feature-lineage object, source accessions, availability timestamps, and PIT ceiling.

The historical Cross-Sectional v2 holdout investigation that motivated this distinction is archived in `docs/archive/cross_sectional_condition_replay.md`.

## Verification

FDRE exposes fail-closed verification helpers including:

- `verify_feature_lineage(...)`;
- `verify_research_panel_lineage(...)`;
- `verify_research_panel_export(...)`;
- `verify_research_screen_lineage(...)`;
- `verify_signal_study_lineage(...)`.

Verification checks source completeness, PIT timestamps, snapshot consistency, deterministic hashes, screen plan/universe lineage replay, and complete signal experiment identity.

Panel and signal artifacts can be verified from the CLI:

```bash
python -m scripts.research.verify_research_lineage panel data/processed/panel.json
python -m scripts.research.verify_research_lineage panel data/processed/panel.csv
python -m scripts.research.verify_research_lineage signal data/processed/signal-study.json
```

Parquet panel verification is supported when the optional data dependencies are installed.

A screen's lineage digest covers the full evaluated issuer universe. Because the public response returns matched rows rather than the complete evaluated panel, complete screen replay requires the corresponding PIT `ResearchPanel`; programmatic replay does not pretend a partial response is self-sufficient.

## Point-in-Time invariant

For every structured feature used in research:

```text
max_source_available_at <= research_timestamp
```

A lineage record with future-dated information, incomplete source timestamps, inconsistent availability ceilings, or a mismatched deterministic hash fails verification.

Historical Universe adds a separate eligibility invariant:

```text
security is eligible in universe_snapshot at research_timestamp
```

Feature lineage proves **what information generated a value**. Universe lineage proves **why the security was eligible to enter the research set**. A credible historical experiment needs both.

## Persistence and infrastructure policy

The lineage implementation deliberately does **not** add:

- a feature-store service;
- a separate feature-registry service;
- a dependency-graph service;
- a workflow orchestrator;
- a new persistence layer;
- a new recurring infrastructure dependency.

PostgreSQL remains the production data plane. Materialized/incremental feature persistence should be added only if measured panel-build cost or cross-workflow reuse demonstrates a concrete need.

The same evidence-first policy applies to Redis, Kafka, Elasticsearch/OpenSearch, and Snowflake: none should be introduced to make the architecture appear larger.

## Evaluation guidance

For sealed benchmarks that score exact lineage replay, capture lineage IDs from a raw `ResearchPanel` built with the **same frozen ticker/security universe, forms, as-of timestamp, sections, amendment policy, and PIT filters as the eventual screen plan**. This preserves holdout sealing without executing semantic retrieval or the screen itself.

For historical-universe experiments, carry both the universe snapshot ID and structured feature/experiment lineage into immutable manifests.
