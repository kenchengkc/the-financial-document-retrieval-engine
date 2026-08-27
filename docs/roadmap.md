# FDRE v2: Hedge-Fund Research Infrastructure Roadmap

FDRE is point-in-time financial research infrastructure designed to stand up to scrutiny from **hedge-fund researchers, quant researchers, research engineers, data engineers, and platform developers**. The product bar is not “interesting AI demo”; it is **credible research infrastructure**: correct historical data, reproducible experiments, auditable lineage, strong retrieval, statistically disciplined signal research, predictable latency, and failure behavior that a professional research team would trust.

The system provides point-in-time SEC ingestion, structured and lexical/vector retrieval, cross-sectional screening, reproducible signal studies, and auditable research lineage under a strict **$15-$20/month total cost envelope**.

> Status reviewed against `main` on **2026-08-27**. This document distinguishes the original target architecture from what is already implemented and deployed.

---

## 0. Audience, Product Bar, and What Should Impress

The primary audience is a technically sophisticated hedge-fund research organization. Roadmap decisions should optimize for the questions that audience will ask during a code review, research review, or systems interview:

- **Can I trust the historical timestamp?** No look-ahead, no silent restatement leakage, explicit `available_at`, reproducible corpus snapshots.
- **Can I reproduce the result?** Dataset/version hashes, source accessions, calculation versions, code identity, deterministic experiment manifests.
- **Can I inspect why a result exists?** Evidence restricted to exact filings, feature lineage, replayable conditions, fail-closed verification.
- **Is the retrieval system actually good?** Frozen benchmarks, sealed holdouts, hard negatives, multi-K metrics, ablations, bounded semantic calls.
- **Is the signal research statistically serious?** Cross-sectional IC, quantiles, long-short spreads, clustered/bootstrap inference, multiple-testing control, walk-forward validation, turnover/cost diagnostics.
- **Will it work under production constraints?** Measured p95 latency, connection/provider decomposition, idempotent jobs, backoff, failure testing, observability.
- **Are architectural choices justified by evidence?** PostgreSQL-first until measurements prove another service is necessary; no infrastructure theater.

### What is *not* a roadmap priority

Do not optimize FDRE around generic chatbot polish, autonomous-agent complexity, more LLM calls, decorative dashboards, broad consumer features, or additional infrastructure merely because it is fashionable. Those are lower-value than research correctness, reproducibility, performance, and engineering depth for the target audience.

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

> **No new recurring service unless FDRE's own empirical metrics demonstrate that the single-PostgreSQL architecture cannot meet a defined quality, research-correctness, or latency SLO.**

---

## 2. Current Phase Status

Legend: **Complete** = target capability is operational for the intended bounded scope; **Partial** = substantial production-quality implementation exists but original roadmap items remain; **Open** = major target capability is still future work.

| Phase | Status | Current state on `main` | Remaining work |
| :--- | :---: | :--- | :--- |
| **0. Evaluation Platform v2** | **Partial / operational** | Multi-K retrieval evaluation, deterministic reports, issuer-level cross-sectional metrics, frozen 28-case v2 development benchmark, sealed 14-case holdout, PIT leakage checks, lineage replay diagnostics, and reproducible run metadata are implemented. | Expand research-task breadth, hard negatives, abstention cases, and benchmark scale without weakening sealed-holdout discipline. |
| **1. Deterministic Typed Query Planner** | **Open** | Strong typed execution plans exist for retrieval and research screens, but callers still construct those plans explicitly. | Add deterministic entity/alias, temporal, section, operation, and modality routing only where it makes research workflows faster and more reliable. |
| **2. Retrieval Engine v2 & Selective Reranking** | **Partial** | PostgreSQL sparse+dense hybrid retrieval, Voyage embeddings, optional reranking, PIT filters, and bounded candidate retrieval are implemented and production-used. | Profile and reduce deployed semantic latency; add measured selective-rerank gating and hard provider-budget fallback if justified. |
| **3. Cross-Sectional Research Engine** | **Complete for bounded scope** | Typed `ResearchScreenPlan`, structured-first filtering, latest eligible PIT filing selection, comparable-prior conditions, at-most-one semantic pass, exact-accession evidence restriction, issuer ranking, lineage manifests, API route, frontend support, frozen evaluations, and live Railway deployment are operational. | Performance/SLO tuning, larger-universe characterization, and more institutional-style screen examples. |
| **4. Point-in-Time Feature Lineage Registry** | **Partial / core lineage complete** | `fdre-panel-v3` feature lineage, source-complete snapshots, calculation versions, source accessions/timestamps, deterministic lineage IDs, screen/signal propagation, export verification, and tamper/fail-closed replay are implemented. | Persistent scalar registry/materialization only if it improves research iteration, dependency inspection, or recomputation cost. |
| **5. Signal Research Laboratory** | **Partial / core lab complete** | Event studies, PIT feature signals, Spearman IC, quantile portfolios, long-short spreads, issuer-cluster bootstrap intervals, Benjamini-Hochberg correction, period diagnostics, experiment manifests, lineage digests, and composite studies exist. | Walk-forward train/test splits, ICIR, turnover, transaction-cost/implementation diagnostics, and stronger promotion gates are high priority. |
| **6. Observability, SLOs & Failure Engineering** | **Open / started** | Real HTTPS latency measurement is operational; temporary stage-level production profiling is being added to isolate semantic-screen latency. Retrieval/research runs already expose deterministic manifests and internal latency fields. | Formal stage spans, repeatable SLO gates, availability measurement, provider/DB failure tests, and production observability. |

---

## 3. Priority Order for the Hedge-Fund Audience

The phase numbers describe architecture, but the work order should follow what most increases credibility with professional researchers and developers.

### Priority A — Research correctness and reproducibility

Maintain zero PIT leakage, exact source lineage, deterministic snapshots, sealed evaluation artifacts, and replayable research results. A fast or sophisticated system that leaks future information is not useful research infrastructure.

### Priority B — Production retrieval quality and latency

Demonstrate that the semantic retrieval path is both accurate and engineered: profile real production stages, remove dominant latency, quantify quality/latency trade-offs, and preserve bounded provider calls.

### Priority C — Institutional-grade signal validation

Extend the existing signal laboratory with walk-forward evaluation, ICIR, turnover, transaction-cost assumptions, robustness across periods/universes, and explicit promotion/rejection criteria. This is one of the highest-value areas for demonstrating quant-research maturity.

### Priority D — Researcher ergonomics without hiding mechanics

Add deterministic planning and workflow improvements that shorten time from hypothesis to reproducible result while keeping the exact plan, inputs, filters, and evidence inspectable.

### Priority E — Production engineering depth

Instrument the system, define SLOs, exercise provider/database/network failures, prove retry/idempotency behavior, and make operational states inspectable.

---

## 4. Execution Sequence From Current State

```text
CURRENT STATE (2026-08-27)

Research correctness / lineage      [strong, continue protecting]
Evaluation platform                 [operational, expand rigor]
Hybrid retrieval                    [live, semantic p95 is active bottleneck]
Cross-sectional research engine     [deployed + evaluated]
Signal laboratory                   [core stack live, validation depth next]
Observability / failure engineering [active next infrastructure layer]
Deterministic NL planner            [useful, but below research/perf rigor]

                         immediate dependency
                                  |
                                  v
              Profile deployed semantic-screen path
                                  |
        panel -> embedding -> retrieval -> rerank -> hydration
                                  |
                                  v
             Reduce semantic p95 without quality loss
                                  |
                                  v
       Formal production SLO + failure/latency observability
                                  |
                                  v
      Walk-forward + ICIR + turnover/cost signal validation
```

---

## 5. Completed / Operational Capabilities

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

These capabilities should be presented as **research controls and engineering guarantees**, not merely feature checkboxes.

---

## 6. Production Baseline After Railway Deployment

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

## 7. Active Milestone: Deployed Semantic-Screen SLO

### Why this matters to the target audience

A hedge-fund research engineer should be able to see not only that semantic retrieval “works,” but where the time goes, what the quality trade-offs are, and why a particular architecture is justified. The profiling/optimization work is therefore itself a portfolio-quality systems artifact.

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

- **semantic-screen HTTPS p95 < 3.0 s** as the immediate milestone.
- Then iterate toward **< 1.5 s** only if achievable inside the cost/quality constraints.
- Preserve structured/change performance.
- Record the before/after stage distribution and the exact quality delta so the optimization is defensible in a technical review.

---

## 8. High-Value Next Research Milestones

### 8.1 Evaluation Platform — institutional-style rigor

Expand beyond the current frozen set with:

- hard-negative filings and near-duplicate disclosures
- issuer/sector confusion cases
- restatement and amendment traps
- exact as-of boundary tests
- abstention / insufficient-evidence cases
- section- and table-specific retrieval
- benchmark versioning with immutable hashes
- retrieval/reranker ablations with confidence intervals where practical

The goal is not a large benchmark for its own sake; it is an evaluation set whose failure modes resemble real research mistakes.

### 8.2 Signal Laboratory — highest-priority quant extension

Extend the current signal stack with:

- explicit train / validation / out-of-sample walk-forward splits
- rolling and period-level Spearman IC
- IC mean, volatility, and **ICIR**
- quantile monotonicity checks
- long-short spread stability
- turnover and holding-period diagnostics
- simple transaction-cost / slippage assumptions
- universe and sector robustness checks
- signal decay by horizon
- multiple-testing-aware promotion rules
- explicit “reject signal” outcomes rather than only successful studies

A research result should be promotable only when it survives temporal stability, implementation-cost, and multiple-testing checks—not because one p-value is attractive.

### 8.3 Feature lineage / registry

Only add dedicated persistent feature-registry infrastructure if it materially improves research iteration or provenance queries. If added, the minimum scalar record is:

- `feature_name`
- `ticker`
- `effective_time`
- `value`
- `source_accessions`
- `calculation_version`
- `code_sha`
- `max_information_timestamp`
- corpus/data snapshot identity

The important artifact is a researcher being able to trace any feature value back to the information set available at that time.

### 8.4 Deterministic research planner

Build a planner only after the current performance/research-validation milestones. It should reduce friction for institutional-style questions while returning an inspectable typed plan containing:

- ticker / issuer resolution
- form and section filters
- as-of / comparable-period semantics
- structured conditions
- semantic query, if actually required
- ranking field
- requested evidence depth

No opaque LLM planning dependency is required.

### 8.5 Observability and failure engineering

Target framework:

- Search p95: `< 1.5 s`
- Answer p95: `< 3.0 s`
- Cached answer p95: `< 100 ms`
- PIT leakage: `0.00`
- API availability: `99.9%`

Add stage spans, production timing distributions, and explicit failure tests for provider timeout, SEC rate limits, database disconnects, partial batch failure, retry/backoff, and idempotent reruns.

---

## 9. Portfolio / Review Artifacts to Produce

For the target audience, the strongest deliverables are measurable engineering and research artifacts that can be inspected independently:

1. **PIT correctness note** — explain `accepted_at` vs `available_at`, amendments/restatements, comparable-period selection, and leakage tests.
2. **Retrieval evaluation report** — frozen benchmark, holdout methodology, dense/sparse/hybrid/rerank ablations, latency-quality frontier.
3. **Production latency profile** — stage-level Railway/Neon/Voyage timings with before/after optimization results.
4. **Research lineage example** — one screen and one signal traced from final result to feature calculation to exact SEC accessions and timestamps.
5. **Signal research report** — walk-forward IC/ICIR, quantiles, long-short, bootstrap inference, FDR correction, turnover/cost, stability and rejection criteria.
6. **Failure-engineering report** — what happens when Voyage, Neon, SEC, or a batch stage fails, including retries and idempotency.

These artifacts make the project legible to experienced researchers and engineers without requiring them to take architectural claims on faith.

---

## 10. Immediate Next Step

**Profile and optimize the deployed semantic `/research/screen` path.**

Measure:

`panel construction -> embedding -> sparse/dense retrieval -> fusion/rerank -> evidence hydration -> serialization`

Then optimize the largest measured contributor and rerun the frozen 28-case development suite through the actual HTTPS endpoint. Record both the stage-level latency change and the retrieval-quality delta. After the production semantic path is understood and materially improved, the next major roadmap investment should be **institutional-grade signal validation: walk-forward evaluation, ICIR, turnover, transaction-cost assumptions, and robustness gates**.
