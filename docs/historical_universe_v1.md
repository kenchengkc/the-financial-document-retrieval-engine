# FDRE Historical Universe v1

FDRE Historical Universe v1 extends point-in-time correctness from filings and features to the **eligible security universe itself**. The initial target is a historically reconstructed S&P 500 research universe with explicit identity history, membership intervals, source provenance, and fail-closed ambiguity handling.

The goal is not to claim a perfect commercial index history from public data. The goal is to make every historical-universe claim auditable, versioned, reproducible, and explicit about the strength of its evidence.

## Why this milestone exists

FDRE already filters filings by SEC information availability and carries source lineage into panels, screens, and signal studies. The remaining research-level bias is that the current S&P 500 seed is a **current-constituent snapshot**. Using today's constituent set for older dates can introduce survivorship and selection bias even when every filing timestamp is otherwise correct.

Historical Universe changes the research contract from:

```text
current constituent list
        +
point-in-time filings
```

to:

```text
historical security identity
        +
historical universe membership
        +
point-in-time filings/features
        +
point-in-time market outcomes
```

A study should only include a security when FDRE can explain why that security was eligible for the named universe at the study's information date.

## Hard constraints

### Research correctness

- All effective intervals use half-open semantics: `[effective_from, effective_to)`.
- A security added after `as_of` must never appear in the snapshot.
- A removed security disappears exactly at `effective_to`.
- Simultaneous share classes remain distinct securities even when they share one SEC issuer/CIK.
- Overlapping active membership or ticker-identity intervals fail closed.
- Missing active identity for an included security fails closed.
- Active provisional membership is not silently omitted. Strict snapshots require verified evidence; provisional evidence requires explicit opt-in.
- Rejected evidence never participates in a snapshot.
- Snapshot identity is deterministic and includes source-provenance hashes.

### Truthfulness

Until historical coverage and source audits justify a stronger claim, documentation should use **historically reconstructed** rather than **survivorship-free**. Public constituent-change records may be incomplete, ambiguous, revised, or contradictory.

### Cost

- Normal total FDRE infrastructure target: **$10–15/month**.
- Hard recurring-cost ceiling: **$20/month**.
- No recurring service may be added merely for architectural fashion or résumé signaling.
- Any material corpus/service expansion requires a documented cost estimate and a measured workload the current stack cannot satisfy economically.

## Data model

The existing `companies` table remains the SEC **issuer** identity keyed by CIK. HU adds a stable listed-security layer because one issuer can have multiple simultaneously listed share classes.

```text
companies
  id
  cik
  current primary ticker
        |
        | 1:N
        v
securities
  id
  company_id
  security_type
  share_class
        |
        +----------------------------+
        |                            |
        | 1:N                        | 1:N
        v                            v
security_identity_periods      universe_memberships
  security_id                    universe_code
  symbol                         security_id
  name                           effective_from
  exchange                       effective_to
  effective_from                 announced_at
  effective_to                   source provenance
  source provenance              verification status
  verification status            confidence
  confidence
```

Ticker is deliberately not a permanent identifier. Tickers, names, and exchanges can change; multiple securities can belong to the same issuer.

### Provenance fields

Every time-varying identity or membership record carries:

- `source`
- `source_url`
- `source_observed_at`
- `source_hash`
- `verification_status`: `verified`, `provisional`, or `rejected`
- `confidence`: `0.0` to `1.0`

The source hash participates in deterministic universe-snapshot identity, so a provenance change produces a different snapshot even if the visible ticker list is unchanged.

## Point-in-time snapshot contract

The target researcher interface is:

```python
snapshot = fdre.universe("sp500", as_of="2020-03-20")
```

The current foundation provides the pure research-domain `build_universe_snapshot(...)` contract. It resolves membership and security identity at an exact date and returns a deterministic snapshot ID.

A future panel interface composes directly with it:

```python
panel = fdre.panel(
    universe="sp500",
    as_of="2020-03-20",
    lookback_years=5,
)
```

The resulting panel must satisfy simultaneously:

1. the security was eligible for the requested universe at `as_of`;
2. the historical symbol/security identity was valid at `as_of`;
3. every filing/fact was available by `as_of`;
4. feature lineage points only to information available by `as_of`;
5. universe and dataset identities are reproducible.

## Historical data architecture

Historical research depth should not imply tripling the interactive vector corpus.

```text
                     FDRE
                      |
          +-----------+-----------+
          |                       |
          v                       v
     PostgreSQL              Cold artifacts
                               if needed
          |                       |
  serving + PIT state         Parquet / compressed
          |                   source artifacts
  - companies                    |
  - securities                   v
  - identity periods       DuckDB / Polars
  - memberships                 |
  - filing metadata             v
  - structured facts      batch research
  - research features
  - lineage/manifests
  - recent text chunks
  - recent embeddings
```

Recent history remains fully searchable. Older history should preferentially store research-relevant sections/facts/features and exact lineage, with bulk historical embeddings created only for a measured use case.

## Infrastructure decision record

Historical Universe intentionally does **not** add Redis, Kafka, Elasticsearch/OpenSearch, or Snowflake.

| Technology | Add only when | HU decision |
| --- | --- | --- |
| Redis | PostgreSQL-backed cache/coordination is a measured load/latency bottleneck | defer |
| Kafka | FDRE becomes a real-time, multi-feed, multi-consumer event platform | defer |
| Elasticsearch/OpenSearch | PostgreSQL cannot meet a defined retrieval quality/latency/scale SLO after optimization | defer |
| Snowflake | research data reaches warehouse-scale/shared-governance needs | defer |
| Parquet + DuckDB/Polars | historical analytical artifacts outgrow convenient serving-table patterns | preferred analytical path |
| Object storage | historical source/Parquet retention materially grows | add only if needed and budgeted |

A new service must remove a measured bottleneck or provide a capability the current stack cannot satisfy economically.

## Milestones

### HU-1 — Security master foundation

**Status: COMPLETE (merged 2026-08-29).**

Implemented:

- stable `securities` entity beneath SEC issuer/CIK;
- historical symbol/name/exchange periods;
- historical universe-membership periods;
- provenance, confidence, and verification status;
- half-open interval semantics;
- deterministic PIT snapshot builder;
- fail-closed overlap, missing-identity, rejected/provisional-evidence behavior;
- Alembic migration and unit tests.

### HU-2 — Membership reconstruction

**Status: ACTIVE.**

Build a reproducible importer/reconciler for public constituent-change evidence.

Acceptance criteria:

- source adapters preserve raw source identity, observation time, and source hash;
- announcement date and implementation/effective date are stored separately;
- additions/removals/replacements materialize into explicit effective intervals;
- historical ticker/name changes resolve to stable securities and SEC CIKs;
- multi-source agreement can promote records to verified;
- ambiguous or conflicting records remain provisional instead of being guessed;
- no inferred historical membership start date is created from the current constituent seed;
- deterministic audit output identifies gaps, overlaps, unresolved identities, share-class ambiguity, and source disagreement;
- current-date membership reconciles against the existing production seed as a **check**, not as historical evidence.

Recommended HU-2 pipeline:

```text
raw source evidence
      |
      v
source-specific adapters
      |
      v
normalized membership events
      |
      v
historical symbol / issuer resolution
      |
      v
cross-source reconciliation
   /         |         \
verified  provisional  rejected
      |
      v
interval materialization
      |
      v
coverage + disagreement audit
```

#### HU-2 promotion gate

HU-2 is complete only when all of the following are true for the intended 2010+ research
window:

- the current constituent catalog has no unmapped symbols and every current listed share class
  resolves to exactly one active stable-security identity;
- at least **95%** of raw membership observations resolve to a stable security, with every
  remainder retained in the published unresolved queue;
- every event boundary used by a strict research snapshot is verified or explicitly adjudicated;
  unresolved boundaries make the affected date/security ineligible rather than guessed;
- every same-date, same-symbol opposing add/remove pair is classified as an evidenced corporate
  action or retained as a conflict;
- at least one pinned, independently sourced complete constituent snapshot at or before
  `2010-01-01` anchors the target window; change records alone are not a starting universe;
- materialization has no unexplained overlaps, missing active identities, or unresolved event
  order; and
- exact replay from the same code and source manifest produces the same audit and snapshot IDs.

The 95% threshold is a pipeline-readiness floor, not permission to fill the remainder. A date is
eligible for strict research only when all membership and identity boundaries affecting that
snapshot meet the stricter evidence rule above. Current measured results and the remediation
queue live in [`eval_results.md`](eval_results.md).

### HU-3 — Universe API / SDK

Expose strict PIT resolution through the research layer.

```python
fdre.universe("sp500", as_of="2020-03-20")
fdre.universe("sp500", as_of="2020-03-20", include_provisional=True)
```

Acceptance criteria:

- deterministic snapshot ID;
- constituent-level source lineage;
- strict/provisional mode visible in outputs;
- API/CLI export to JSON and Parquet;
- explicit PIT leakage tests;
- snapshot replay verification;
- research-panel composition.

### HU-4 — 10–15 year research archive

Extend research history without proportionally expanding embeddings.

Acceptance criteria:

- historical filings/features available for the reconstructed universe;
- source accessions/availability timestamps retained;
- historical market outcomes cached reproducibly;
- research panels export to Parquet;
- storage/compute cost measured before and after backfill;
- normal recurring spend remains inside the $10–15 target and below $20.

### HU-5 — Institutional flagship rerun

Rerun the precommitted risk-churn acceleration study against the historical universe and longer history **without changing methodology to manufacture a positive result**.

Acceptance criteria:

- at least 4 statistically usable sealed OOS folds, preferably 4–6+;
- primary 1:63 horizon evaluable across multiple periods;
- secondary 1:21 and 1:126 horizons retained;
- turnover and 5/10/25/50 bp implementation costs retained;
- sector/temporal robustness retained;
- result remains honestly `PROMOTE`, `REJECT`, or `INSUFFICIENT`;
- universe snapshot identity is included in the immutable experiment manifest.

## Follow-on work after HU

Once historical universe correctness and depth are credible, prioritize:

1. portfolio implementation with sector/beta neutrality, liquidity constraints, turnover, and gross/net performance;
2. falsification harness with randomized signals/dates, intentional timestamp-leak tests, placebo universes, and parameter sensitivity;
3. researcher-facing Python SDK for panels, signals, walk-forward studies, and experiment replay;
4. larger hard-negative retrieval/research evaluation suites;
5. formal production fault injection and observability.

These come after universe correctness because better portfolio statistics on a biased universe create false precision.

## Cost guardrail

Before any change that materially enlarges storage or adds infrastructure, record:

```text
current monthly run rate
new recurring service cost
expected GB stored
expected batch compute/runtime
expected provider-call cost
measured bottleneck being solved
cheaper alternative considered
rollback condition
```

If projected normal spend exceeds **$15/month**, the change needs explicit justification. If it can exceed **$20/month**, it is out of scope unless cost is recovered elsewhere.
