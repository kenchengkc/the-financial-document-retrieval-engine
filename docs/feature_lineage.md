# Point-in-Time Feature Lineage

FDRE's research lineage contract is designed to make structured research outputs reproducible without introducing a separate feature-store service.

## Contract

Every computed panel feature carries a `FeatureLineage` record containing:

- feature name
- feature-specific calculation version
- calculation parameters
- exact source filing accessions
- per-source availability timestamps
- maximum information timestamp
- corpus snapshot ID
- deterministic SHA-256 lineage ID

The lineage ID fingerprints the feature definition and its point-in-time source identity. Changing a source filing, source timestamp, calculation version, parameter, or corpus snapshot changes the lineage ID.

## Propagation

The same lineage identity is propagated through the research stack:

1. **Research panel** — every computed feature has an independently verifiable lineage record.
2. **Cross-sectional screen** — every structured condition references the exact current/prior feature lineage used for the decision. The screen manifest includes a deterministic `feature_lineage_digest` over the structured inputs evaluated across the PIT universe.
3. **Signal study** — scored filing events carry the selected feature lineage. Complete studies expose accession-to-lineage IDs, a lineage digest, and an experiment key that changes when the underlying feature inputs change.

Semantic-provider output is intentionally not represented as deterministic feature lineage. The screen digest fingerprints structured research inputs, not potentially nondeterministic retrieval-provider output.

## Verification

Part 6.4 adds fail-closed verification helpers:

- `verify_feature_lineage(...)`
- `verify_research_panel_lineage(...)`
- `verify_research_panel_export(...)`
- `verify_research_screen_lineage(...)`
- `verify_signal_study_lineage(...)`

Verification checks source completeness, PIT timestamps, snapshot consistency, deterministic hashes, screen plan/universe lineage replay, and complete signal experiment identity.

Panel and signal artifacts can be verified from the CLI:

```bash
python -m scripts.verify_research_lineage panel data/processed/panel.json
python -m scripts.verify_research_lineage panel data/processed/panel.csv
python -m scripts.verify_research_lineage signal data/processed/signal-study.json
```

Parquet panel verification is supported when the existing optional `data` dependencies are installed.

A screen's lineage digest covers the full evaluated issuer universe. Because the public screen response only returns matched rows, complete screen replay requires the corresponding PIT `ResearchPanel` object and is therefore exposed programmatically rather than pretending the response can self-verify from incomplete inputs.

## Point-in-Time Invariant

For every structured feature used in research:

```text
max_source_available_at <= research_timestamp
```

A lineage record with future-dated information, incomplete source timestamps, inconsistent availability ceilings, or a mismatched deterministic hash fails verification.

## Scope and Non-Goals

The current lineage implementation deliberately does **not** add:

- a feature-store service
- a feature registry database table
- a dependency-graph service
- a workflow orchestrator
- a new persistence layer
- a new recurring infrastructure dependency

PostgreSQL remains the single production data plane. Materialized/incremental feature persistence should be added only if measured panel-build cost or research workflow reuse demonstrates a concrete need.

## Part 6 Status

- 6.1 — per-feature versioned PIT lineage: complete
- 6.2 — cross-sectional screen lineage propagation: complete
- 6.3 — signal-study lineage propagation: complete
- 6.4 — artifact verification and reproducibility closeout: complete once merged

The next evaluation work should use this contract rather than expand it: re-ground cross-sectional evidence onto each screen-selected filing, add independently reviewed structured/delta cases, and run a Cross-Sectional v2 benchmark that measures condition correctness, lineage completeness, PIT leakage, issuer ranking, evidence grounding, and real `/research/screen` latency.
