# FDRE Historical Universe v1

FDRE Historical Universe v1 extends point-in-time correctness from filings and features to the
**eligible security universe itself**. The initial target is a historically reconstructed S&P 500
research universe with explicit identity history, membership intervals, source provenance, and
fail-closed ambiguity handling.

The objective is not to claim a perfect commercial index history from public data. The objective is
to make every historical-universe claim auditable, versioned, reproducible, and honest about the
strength of its source evidence.

## 1. Why this is the next milestone

FDRE already filters filings by SEC information availability and carries source lineage into panels,
screens, and signal studies. The remaining research-level bias is that the current S&P 500 seed is a
**current-constituent snapshot**. Using today's constituent set for older dates can introduce
survivorship and selection bias even when every filing timestamp is otherwise correct.

Historical Universe v1 changes the research contract from:

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

A study should only include a security if FDRE can prove that the security was eligible for the
named universe at the study's information date.

## 2. Hard constraints

### Research correctness

- All effective intervals use half-open semantics: `[effective_from, effective_to)`.
- A security added after `as_of` must never appear in the snapshot.
- A removed security disappears exactly at `effective_to`.
- Simultaneous share classes remain distinct securities even when they share one SEC issuer/CIK.
- Overlapping active membership or ticker-identity intervals fail closed.
- Missing active identity for an included security fails closed.
- Active provisional membership is not silently omitted. Strict snapshots require verification;
  provisional evidence requires an explicit opt-in.
- Rejected evidence never participates in a snapshot.
- Snapshot identity is deterministic and includes source-provenance hashes.

### Truthfulness

Until historical coverage and source audits justify a stronger claim, documentation should use
**"historically reconstructed"** rather than **"survivorship-free"**. Public constituent-change
records may be incomplete, ambiguous, revised, or disagree across sources. FDRE should expose those
limitations instead of silently filling gaps.

### Cost

- Normal total FDRE infrastructure target: **$10-$15/month**.
- Hard recurring-cost ceiling: **$20/month**.
- No new recurring service is permitted merely for architectural fashion or resume signaling.
- Any service or corpus expansion that could materially increase recurring spend requires a
  documented cost estimate and a measured workload that the current stack cannot satisfy.

## 3. Data model

The existing `companies` table remains the SEC **issuer** identity keyed by CIK. Historical Universe
v1 adds a separate stable listed-security layer because one issuer can have multiple simultaneously
listed share classes.

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

This deliberately avoids using ticker as a permanent identifier. Tickers can change, names can
change, exchanges can change, and multiple securities can belong to the same issuer.

### Source provenance fields

Every time-varying identity or membership record carries:

- `source`
- `source_url`
- `source_observed_at`
- `source_hash`
- `verification_status`: `verified`, `provisional`, or `rejected`
- `confidence`: `0.0` to `1.0`

The source hash is part of deterministic universe-snapshot identity so a provenance change produces
a different snapshot even when the visible ticker list is unchanged.

## 4. Point-in-time snapshot contract

The target researcher interface is:

```python
snapshot = fdre.universe(
    "sp500",
    as_of="2020-03-20",
)
```

The first implementation layer is the pure research-domain function
`build_universe_snapshot(...)`. It resolves membership and security identity at an exact date and
returns a deterministic `snapshot_id`.

A future panel interface will compose directly with it:

```python
panel = fdre.panel(
    universe="sp500",
    as_of="2020-03-20",
    lookback_years=5,
)
```

The resulting panel must satisfy all of the following simultaneously:

1. the security was eligible for the requested universe at `as_of`;
2. the historical symbol/security identity was valid at `as_of`;
3. every filing/fact was available by `as_of`;
4. feature lineage points only to information available by `as_of`;
5. the universe snapshot and research dataset carry reproducible hashes.

## 5. Historical data architecture

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

### Recent interactive corpus

Keep the recent filing window fully parsed, chunked, and embedded for live retrieval.

### Older research history

For roughly 10-15 years of research history, prefer:

```text
filing
  -> parse required sections / structured facts
  -> calculate research features
  -> persist feature + exact lineage
  -> optionally persist compressed source / Parquet artifact
  -> do not create bulk embeddings unless a measured research use case needs them
```

This lets statistical history grow much faster than vector-storage cost.

## 6. Infrastructure decision record

Historical Universe v1 intentionally does **not** add Redis, Kafka, Elasticsearch, or Snowflake.
Each remains available behind a measured trigger.

| Technology | What it would solve | Add only when | HU v1 decision |
| --- | --- | --- | --- |
| Redis | hot ephemeral cache, locks, coordination | PostgreSQL-backed cache/coordination becomes a measured latency or load bottleneck | Do not add |
| Kafka | durable high-throughput multi-consumer event streams | FDRE becomes a genuine real-time multi-feed, multi-consumer platform | Do not add |
| Elasticsearch | dedicated lexical/vector/hybrid search | PostgreSQL cannot meet a defined retrieval quality/latency/scale SLO after measured optimization | Do not add |
| Snowflake | shared large-scale analytical warehouse | research data reaches hundreds of GB/TB, repeated large joins, concurrent researchers, or governance requirements | Do not add |
| Parquet + DuckDB/Polars | cheap columnar batch analytics | historical research artifacts outgrow convenient PostgreSQL serving patterns | Preferred analytical path |
| Object storage | cheap immutable bulk/cold artifacts | historical source or Parquet retention materially grows | Add only if needed and budgeted |

The engineering principle is simple: **a new service must remove a measured bottleneck or provide a
capability that the existing stack cannot satisfy economically.**

## 7. Milestones

### HU-1 — Security master foundation

Status: **in progress**.

Acceptance criteria:

- stable `securities` entity beneath SEC issuer/CIK;
- historical symbol/name/exchange periods;
- historical universe membership periods;
- provenance, confidence, and verification status on time-varying records;
- half-open interval semantics;
- deterministic PIT snapshot builder;
- fail-closed overlap, missing-identity, and provisional-evidence behavior;
- Alembic migration and unit tests.

### HU-2 — Membership reconstruction

Build a reproducible importer for public constituent-change evidence.

Acceptance criteria:

- source adapters preserve raw source identity and observation time;
- additions/removals become explicit effective intervals;
- ticker/name changes resolve to stable securities and SEC CIKs;
- ambiguous records remain provisional;
- no inferred membership start date is created from a current constituent snapshot;
- coverage/audit report identifies gaps, overlaps, unresolved identities, and source disagreements.

The existing current S&P 500 seed may be used as a **current snapshot check**, not as evidence that a
security belonged to the index before the seed's observation date.

### HU-3 — Universe API / SDK

Expose strict point-in-time resolution through the research layer.

Target interfaces:

```python
fdre.universe("sp500", as_of="2020-03-20")
fdre.universe("sp500", as_of="2020-03-20", include_provisional=True)
```

Acceptance criteria:

- deterministic `snapshot_id`;
- constituent-level source lineage;
- strict/provisional mode visible in outputs;
- API/CLI export to JSON and Parquet;
- explicit PIT leakage tests;
- snapshot replay verification.

### HU-4 — 10-15 year research archive

Extend research history without proportionally expanding embeddings.

Acceptance criteria:

- historical filings/features available for the reconstructed universe;
- source accessions and availability timestamps retained;
- historical market outcomes cached reproducibly;
- research panels export to Parquet;
- storage/compute cost measured before and after backfill;
- normal recurring FDRE spend remains inside the $10-$15 target and below the $20 ceiling.

### HU-5 — Institutional flagship rerun

Rerun the precommitted risk-churn acceleration study against the historical universe and longer
history without changing the methodology to manufacture a positive result.

Acceptance criteria:

- enough temporal history for at least 4 statistically usable sealed OOS folds, preferably 4-6+;
- primary 1:63 horizon evaluable across multiple regimes;
- secondary 1:21 and 1:126 horizons retained;
- turnover and 5/10/25/50 bp implementation costs retained;
- sector and temporal robustness retained;
- result remains honestly `PROMOTE`, `REJECT`, or `INSUFFICIENT`;
- universe snapshot identity is included in the immutable experiment manifest.

## 8. Follow-on work after HU

Once the historical universe and depth are credible, the highest-value extensions are:

1. portfolio implementation with sector/beta neutrality, liquidity constraints, turnover, and
   gross/net performance;
2. a falsification harness with randomized signals/dates, intentional timestamp-leak tests,
   placebo universes, and parameter sensitivity;
3. a researcher-facing Python SDK for panels, signals, walk-forward studies, and experiment replay;
4. larger hard-negative retrieval/research evaluation suites;
5. formal production fault injection and observability.

These should come after universe correctness because better portfolio statistics on a biased
historical universe would create false precision.

## 9. Cost guardrail

Before any Historical Universe change that materially enlarges storage or adds infrastructure,
record:

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

If the projected normal monthly run rate exceeds **$15**, the change needs an explicit justification.
If it can exceed **$20**, it is out of scope unless the architecture is changed to recover the cost
elsewhere.

The cost constraint is itself part of the project: FDRE should demonstrate that institutional-style
research controls do not require institutional-scale infrastructure spend.
