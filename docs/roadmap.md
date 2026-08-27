# FDRE v2: Cost-Constrained Research Infrastructure Roadmap

FDRE is financial research infrastructure designed for **Research/Data Engineering** and **Quant Research Engineering**. It provides point-in-time financial document ingestion, structured and lexical/vector retrieval, cross-sectional screening, reproducible signal studies, and auditable research lineage under a strict **$15-$20/month total cost envelope**.

> Status reviewed against `main` on **2026-08-27**. This document distinguishes the original target architecture from what is already implemented and deployed.

---

## 1. Financial SLO & Architecture Budget

| Component | Target Monthly Spend | Implementation / Constraint |
| :--- | :---: | :--- |
| **PostgreSQL (`pgvector`) on Neon** | $8-$10 | Unified store for metadata, lexical (`tsvector` GIN), vectors (`halfvec` HNSW), typed facts, traces, and experiment manifests. |
| **Backend on Railway** | within total envelope | FastAPI production service; `/research/screen` is deployed from `main`. |
| **Frontend on Vercel** | $0 | Static / ISR deployment on Vercel hobby tier. |
| **CI / Evals / Batch Jobs** | $0 | GitHub Actions standard public runners. |
| **Observability & Tracing** | $0 | Prefer OpenTelemetry + Grafana Cloud Free tier + PostgreSQL trace spans; full production integration remains open. |
| **Deterministic Query Planner** | $0 | Typed entity/temporal/intent parser without LLM overhead; general natural-language planner remains open. |
| **Feature Lineage** | $0 | Per-feature source pointers, hashes, calculation versions, snapshot identity, and verification are implemented; persistent registry semantics remain open. |
| **Batch Signal Laboratory** | $0 | Local execution and scheduled GitHub Actions batch runs. |
| **Embedding Queries (Voyage)** | $0-$1 | Query embedding for dense search at portfolio traffic. |
| **Selective Reranking** | $0-$3 | Reranking exists; selective gating and a hard monthly circuit breaker remain open. |
| **LLM Generation** | $0 | `ANSWER_GENERATOR=mock` / deterministic citation synthesis. |
| **Target Normal Total** | **$9-$15 / mo** | |
| **Hard Production Ceiling** | **$20 / mo** | New recurring services require measured justification. |

### Core Architectural Principle

> **No new recurring service unless FDRE's own empirical metrics demonstrate that the single-PostgreSQL architecture cannot meet a defined quality or latency SLO.**

---

## 2. Current Phase Status

Legend: **Complete** = target capability is operational for the intended bounded scope; **Partial** = substantial production-quality implementation exists but original roadmap items remain; **Open** = major target capability is still future work.

| Phase | Status | Current state on `main` | Remaining work |
| :--- | :---: | :--- | :--- |
| **0. Evaluation Platform v2** | **Partial / operational** | Multi-K retrieval evaluation, deterministic reports, issuer-level cross-sectional metrics, frozen 28-case v2 development benchmark, sealed 14-case holdout, PIT leakage checks, lineage replay diagnostics, and reproducible run metadata are implemented. | Original 500-1,000 question task-stratified scale is not reached; continue benchmark expansion without weakening sealed-holdout discipline. |
| **1. Deterministic Typed Query Planner** | **Open** | Strong typed execution plans exist for retrieval and research screens, but callers still construct those plans explicitly. | Add deterministic natural-language entity/alias, temporal, section, operation, and modality routing; no LLM planner required. |
| **2. Retrieval Engine v2 & Selective Reranking** | **Partial** | PostgreSQL sparse+dense hybrid retrieval, Voyage embeddings, optional reranking, PIT filters, and bounded candidate retrieval are implemented and production-used. | Profile and reduce deployed semantic latency; add measured selective-rerank gating and hard provider-budget fallback if justified. |
| **3. Cross-Sectional Research Engine** | **Complete for bounded scope** | Typed `ResearchScreenPlan`, structured-first filtering, latest eligible PIT filing selection, comparable-prior conditions, at-most-one semantic pass, exact-accession evidence restriction, issuer ranking, lineage manifests, API route, frontend support, frozen evaluations, and live Railway deployment are operational. | Performance/SLO tuning and broader universe/load characterization; do not add a general DSL unless measured use cases require it. |
| **4. Point-in-Time Feature Lineage Registry** | **Partial / core lineage complete** | `fdre-panel-v3` feature lineage, source-complete snapshots, calculation versions, source accessions/timestamps, deterministic lineage IDs, screen/signal propagation, export verification, and tamper/fail-closed replay are implemented. | Original persistent scalar registry, incremental materialization policy, and explicit dependency-graph validation are not yet implemented as a dedicated registry layer. |
| **5. Signal Research Laboratory** | **Partial / core lab complete** | Event studies, PIT feature signals, Spearman IC, quantile portfolios, long-short spreads, issuer-cluster bootstrap intervals, Benjamini-Hochberg correction, period diagnostics, experiment manifests, lineage digests, and composite studies exist. | Formal walk-forward train/test splits, ICIR aggregation, turnover reporting, and stronger promotion gates remain. |
| **6. Observability, SLOs & Failure Engineering** | **Open / started** | Production route checks and real HTTPS latency measurement are now possible; retrieval/research runs already expose deterministic manifests and internal latency fields. | Add stage-level semantic-screen timing, OpenTelemetry/Grafana integration, formal SLO gates, availability measurement, and failure/chaos injection. |

---

## 3. Execution Sequence From Current State

The original phase numbering remains useful as an architectural map, but implementation has progressed non-linearly. Work should now follow measured dependencies rather than restarting at Phase 0.

```text
CURRENT STATE (2026-08-27)

Phase 0  Evaluation platform          [operational; scale expansion remains]
Phase 1  Deterministic NL planner     [open]
Phase 2  Retrieval v2                 [hybrid live; semantic SLO work active]
Phase 3  Cross-sectional engine       [deployed + evaluated]
Phase 4  Feature lineage              [core contract + verification live]
Phase 5  Signal laboratory            [core research stack live]
Phase 6  Observability / failure eng. [next active infrastructure layer]

                         immediate dependency
                                  |
                                  v
              Profile deployed semantic-screen path
                                  |
        panel -> embedding -> retrieval -> rerank -> hydration
                                  |
                                  v
             Reduce semantic p95 toward production SLO
                                  |
                                  v
          Formalize stage spans + repeatable HTTP SLO gate
```

---

## 4. Completed / Operational Capabilities

### Evaluation and benchmark discipline

- Multi-K retrieval evaluation and deterministic report artifacts.
- Cross-sectional issuer Recall/Precision, evidence Recall, condition correctness, exact lineage replay, PIT leakage, latency, and semantic-call metrics.
- Frozen Cross-Sectional v2 development set: **28 cases** across semantic, temporal, structured, change, and semantic+structured tasks.
- Sealed Cross-Sectional v2 holdout: **14 cases**, with explicit first-run freeze and hash guards.
- Holdout diagnostics distinguish decision/source correctness from snapshot-scoped exact lineage-ID replay without rewriting historical results.

### Cross-sectional research execution

- `POST /research/screen` is deployed on Railway from `main`.
- Structured conditions execute before semantic search.
- Structured-only and change screens use **zero semantic provider calls**.
- Semantic/mixed screens use at most one bounded semantic search call.
- Returned semantic evidence is constrained to the exact PIT-selected filing accession.
- Screen results carry source accessions, condition values, feature provenance, lineage identity, snapshot IDs, and maximum-information timestamps.

### Feature lineage and reproducibility

- Feature-specific calculation versions and deterministic lineage IDs.
- Source-complete PIT corpus snapshots including comparable-prior inputs.
- Current/prior lineage propagation into screen conditions.
- Signal-study lineage digests and experiment identity.
- Fail-closed verification of panel exports, screen lineage replay, feature hashes, and signal manifests.

### Signal research

- Event-time alignment that respects information availability.
- Cross-sectional Spearman information coefficient.
- Quantile and long-short portfolio summaries.
- Issuer-cluster bootstrap confidence intervals / p-values.
- Benjamini-Hochberg false-discovery correction across tested windows.
- Period-level stability diagnostics and reproducible experiment persistence.

---

## 5. Production Baseline After Railway Deployment

On **2026-08-27**, the frozen 28-case Cross-Sectional v2 development suite was executed sequentially through the real HTTPS endpoint `POST https://api.thefdre.com/research/screen` against the deployed Railway service.

### Quality

- HTTP success: **28/28**
- Issuer Recall@1: **0.928571**
- Issuer Recall@3: **1.000000**
- Issuer Recall@5: **1.000000**
- Evidence Recall@1: **0.833333**
- Evidence Recall@3 / @5: **0.944444 / 0.944444**
- Reviewed condition correctness: **100%**
- Exact lineage replay: **100%**
- Strict condition grounding: **100%**
- PIT leakage: **0.0%**
- Mean/max semantic calls: **0.643 / 1**

### Latency

| Slice | API p95 | End-to-end HTTPS p95 |
| :--- | ---: | ---: |
| **Overall (28)** | **2.691 s** | **2.815 s** |
| **Semantic (10)** | **3.588 s** | **3.956 s** |
| **Semantic + structured (5)** | **1.810 s** | **1.919 s** |
| **Structured (5)** | **1.140 s** | **1.247 s** |
| **Change (5)** | **0.946 s** | **1.052 s** |
| **Temporal (3)** | **2.030 s** | **2.159 s** |

Typical HTTP/proxy/network overhead was modest (**~109 ms p50, ~134 ms p95**), so the dominant semantic latency is inside the deployed application/database/provider path rather than the public HTTP layer.

---

## 6. Active Milestone: Deployed Semantic-Screen SLO

### Objective

Bring deployed semantic-screen p95 down from approximately **3.96 s HTTPS** toward the intended search SLO while preserving frozen-development quality, one-call provider bounds, PIT correctness, and the existing cost envelope.

### Required profiling split

Instrument and measure, for semantic and semantic+structured screens:

1. **Panel construction / PIT filing selection**
2. **Embedding request**
3. **Sparse retrieval**
4. **Dense retrieval**
5. **Hybrid fusion / candidate filtering**
6. **Reranker** (when enabled)
7. **Evidence hydration / ORM loading**
8. **Response construction and serialization**

Also separate first-request connection/setup effects from warm steady-state behavior and record enough context to distinguish:

- Railway <-> Neon network/locality and connection setup
- Voyage embedding/provider latency
- SQL execution and result hydration
- reranker latency
- Python-side fusion/filtering/serialization

### Optimization gate

Do not introduce Redis, Elasticsearch/OpenSearch, a second vector database, or another recurring service for this work. Optimize the measured dominant stage first. Any quality-affecting retrieval change must rerun the frozen 28-case development suite and preserve:

- Issuer Recall@3 / @5 = **1.0 / 1.0**
- PIT leakage = **0**
- condition correctness = **100%**
- semantic calls <= **1 per screen**

### Target

Initial target for this milestone:

- **semantic-screen HTTPS p95 < 3.0 s**, then iterate toward the roadmap search SLO of **< 1.5 s** only if achievable inside the cost/quality constraints.
- Maintain structured/change warm performance without regression.

---

## 7. Later Phase Details

### Phase 0: Evaluation Platform v2 - remaining scope

Continue expanding task diversity and sample size without changing frozen v2 artifacts. New benchmark versions should add direct factual/XBRL, semantic disclosure, comparative, cross-sectional, temporal, hard-negative, and abstention cases with explicit dataset/version hashes.

### Phase 1: Deterministic Typed Query Planner

Build a fast deterministic parser that can resolve:

- tickers and aliases
- document types (`10-K`, `10-Q`)
- target sections (Risk Factors, MD&A, Financial Statements, Notes)
- temporal windows (latest, prior period, as-of date, comparable period)
- operation (`lookup`, `screen`, `compare`, `thematic_scan`)
- modality (`xbrl_facts`, narrative text, tables)
- whether semantic retrieval/reranking is necessary

This planner must not become an LLM dependency.

### Phase 2: Retrieval Engine v2 & Selective Reranking - remaining scope

After semantic-path profiling, use measured evaluation deltas to decide whether reranking should be bypassed for easy queries and whether a provider-budget circuit breaker is worth implementing. Fallback must remain deterministic hybrid retrieval rather than request failure.

### Phase 4: Persistent Feature Registry - remaining scope

Only add dedicated persistence if the existing reproducible panel/export/experiment contracts show a real recomputation or lineage-query bottleneck. If added, the minimum scalar record is `feature_name`, `ticker`, `effective_time`, `value`, `source_accessions`, `calculation_version`, `code_sha`, and `max_information_timestamp`.

### Phase 5: Signal Research Laboratory - remaining scope

Add explicit walk-forward splits, ICIR over time, turnover/implementation-cost diagnostics, and promotion criteria based on stability/monotonicity rather than isolated p-values.

### Phase 6: Observability, SLOs & Failure Engineering

Target framework after the semantic profile is trustworthy:

- Search p95: `< 1.5 s`
- Answer p95: `< 3.0 s`
- Cached answer p95: `< 100 ms`
- PIT leakage: `0.00`
- API availability: `99.9%`

Add OpenTelemetry stage spans, Grafana Cloud free-tier dashboards if useful, and explicit failure-injection tests for provider timeout, SEC rate limits, partial batch failures, retry/backoff, idempotency, and network disconnects.

---

## 8. Immediate Next Step

**Profile and optimize the deployed semantic `/research/screen` path.**

Measure:

`panel construction -> embedding -> sparse/dense retrieval -> fusion/rerank -> evidence hydration -> serialization`

Then optimize the largest measured contributor and rerun the frozen 28-case development suite through the actual HTTPS endpoint. Do not move to a new roadmap phase until the production semantic latency regression relative to the executor-only baseline is understood and materially reduced.
