# FDRE v2: Cost-Constrained Research Infrastructure Roadmap

FDRE is financial research infrastructure designed for **Research/Data Engineering** and **Quant Research Engineering**. It provides point-in-time financial document ingestion, structured and lexical/vector retrieval, cross-sectional screening, and reproducible signal studies—engineered under a strict **$15–$20/month total cost envelope**.

---

## 1. Financial SLO & Architecture Budget

| Component | Target Monthly Spend | Implementation / Constraint |
| :--- | :---: | :--- |
| **PostgreSQL (`pgvector`) on Neon** | $8 – $10 | Unified store for metadata, lexical (`tsvector` GIN), vectors (`halfvec` HNSW), typed facts, traces, and experiment manifests. |
| **Frontend on Vercel** | $0 | Static / ISR deployment on Vercel hobby tier. |
| **CI / Evals / Batch Jobs** | $0 | GitHub Actions standard public runners. |
| **Observability & Tracing** | $0 | OpenTelemetry + Grafana Cloud Free tier + PostgreSQL trace spans. |
| **Deterministic Query Planner** | $0 | Typed entity/temporal/intent parser without LLM overhead. |
| **Feature Lineage Registry** | $0 | Stored reference pointers, hashes, and calculation versions in PostgreSQL. |
| **Batch Signal Laboratory** | $0 | Local execution and scheduled GitHub Actions batch runs. |
| **Embedding Queries (Voyage)** | $0 – $1 | Query embedding for dense search at portfolio traffic. |
| **Selective Reranking** | $0 – $3 | Invoked on hard queries only, with hard monthly budget cap and hybrid fallback. |
| **LLM Generation** | $0 | `ANSWER_GENERATOR=mock` / deterministic citation synthesis. |
| **Target Normal Total** | **$9 – $15 / mo** | |
| **Hard Production Ceiling** | **$20 / mo** | Enforced via budget circuit breakers and fallback routing. |

### Core Architectural Principle
> **No new recurring service unless FDRE's own empirical metrics demonstrate that the single-PostgreSQL architecture cannot meet a defined quality or latency SLO.**

---

## 2. Phase Breakdown & Execution Sequence

```
                                  Execution Flow
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 0: Evaluation Platform v2 ($0)                                            │
│ ├─ Task-stratified benchmark (500–1,000 queries)                                │
│ └─ Multi-metric eval CLI (Recall@5/10/20, MRR, nDCG@10, PIT leakage, Latency)    │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 1: Deterministic Typed Query Planner ($0)                                 │
│ ├─ Entity & alias resolution (exact boundary matching)                          │
│ ├─ Temporal parser (fiscal period, YoY, comparable period)                      │
│ └─ Strategy classifier (XBRL first, Lexical/Dense, Screen, or Comparison)       │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 2: Retrieval Engine v2 & Selective Reranking ($0–$3/mo)                   │
│ ├─ Hybrid fusion optimization over existing 2.71M chunks                        │
│ ├─ Selective reranking gate (evaluated on hard/ambiguous queries only)          │
│ └─ Hard budget circuit breaker (graceful fallback to hybrid search)             │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 3: Cross-Sectional Research Engine in PostgreSQL ($0)                     │
│ ├─ Single-DB multi-issuer screening DSL                                         │
│ ├─ ANN candidate generation + issuer diversification                            │
│ └─ Zero-leakage temporal point-in-time snapshots                                │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 4: Point-in-Time Feature Lineage Registry ($0)                            │
│ ├─ Feature definition schemas (source accessions, calculation version, Git SHA) │
│ ├─ Incremental recomputation & materialized PIT panel exports                   │
│ └─ Dependency graph validation                                                  │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 5: Signal Research Laboratory ($0)                                        │
│ ├─ Walk-forward cross-validation splits                                         │
│ ├─ Spearman Rank IC, ICIR, quantile spreads, bootstrap intervals               │
│ └─ Multiple-testing treatment (Benjamini-Hochberg / FDR) & experiment manifests │
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 6: Observability, SLOs & Failure Engineering ($0)                         │
│ ├─ OpenTelemetry spans & Grafana Cloud Free integration                         │
│ ├─ Formal latency SLO gates (p95 < 1.5s search, p95 < 3s answer)                │
│ └─ Chaos & failure injection (provider timeout, backoff, idempotency)           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Project Details

### Phase 0: Evaluation Platform v2
- **Objective**: Establish the immutable baseline before optimizing retrieval.
- **Dataset Contract**: 500–1,000 task-stratified human-reviewed questions:
  - *Direct factual* (XBRL metric lookups)
  - *Semantic disclosure* (Risk Factors, MD&A)
  - *Comparative* (Period-over-period, issuer comparisons)
  - *Cross-sectional* (Multi-company theme scans)
  - *Temporal* (As-of point-in-time constraints)
  - *Hard negatives* (Same vocabulary, wrong year/quarter/issuer)
  - *Abstentions* (Forecasts, insider data, unsupported claims)
- **Metrics Tracked**: Recall@5/10/20, MRR, nDCG@10, Issuer Recall, Citation Precision, Abstention Macro-F1, PIT Leakage Rate (must be 0), and Latency p50/p95/p99.
- **Deliverable**: `fdre eval retrieval --suite <name>` storing run manifests (Git SHA, dataset version, embeddings/reranker config, latencies, and metrics).

### Phase 1: Deterministic Typed Query Planner
- **Objective**: Stop treating every query as an unconstrained semantic search.
- **Design**: Fast, deterministic ($0 compute) parser resolving:
  - Tickers & aliases
  - Document types (10-K, 10-Q)
  - Target sections (Risk Factors, MD&A, Financial Statements, Notes)
  - Temporal windows (latest, prior year, as-of date)
  - Operation type (`lookup`, `screen`, `compare`, `thematic_scan`)
  - Modality routes (`xbrl_facts`, `narrative_text`, `tables`)
  - Reranking necessity flag (`rerank: bool`)

### Phase 2: Retrieval Engine v2 & Selective Reranking
- **Selective Execution**:
  - *Bypassed* (Direct Hybrid): Ticker + Metric, known accession, exact section, XBRL fact query.
  - *Reranked*: Semantic disclosure, subtle paraphrases, ambiguous cross-sectional queries.
- **Budget Circuit Breaker**:
  - Configurable hard limit (e.g. `RERANK_MONTHLY_BUDGET_USD=3.00`).
  - When monthly quota is exhausted, system logs an alert and automatically falls back to unranked hybrid retrieval without failing user requests.

### Phase 3: Cross-Sectional Research Engine in PostgreSQL
- **Objective**: Execute multi-company semantic and fundamental screens without adding Elasticsearch, Redis, or distributed clusters.
- **Capabilities**:
  - Issuer diversification in SQL before ranking.
  - Filtered ANN execution over halfvec indexes.
  - Composable research filters (e.g., disclosure changes AND year-over-year margin momentum).

### Phase 4: Point-in-Time Feature Lineage Registry
- **Objective**: Institutional-grade feature lineage with minimal storage cost.
- **Schema**: Store lightweight scalar records containing `feature_name`, `ticker`, `effective_time`, `value`, `source_accessions`, `calculation_version`, `code_sha`, and `max_information_timestamp`.

### Phase 5: Signal Research Laboratory
- **Objective**: Academic and systematic-fund level research rigor.
- **Standards**:
  - Walk-forward rolling train/test splits.
  - Pearson & Spearman Rank Information Coefficients (IC), IC Information Ratio (ICIR).
  - Quantile spread returns and turnover.
  - False Discovery Rate (FDR) multiple-testing corrections.
  - Honest reporting of null results and statistical insignificance.

### Phase 6: Observability, SLOs & Failure Injection
- **SLO Framework**:
  - Search p95: `< 1.5 s`
  - Answer p95: `< 3.0 s`
  - Cached Answer p95: `< 100 ms`
  - Point-in-time Leakage: `0.00`
  - API Availability: `99.9%`
- **Failure Injection**: Verify resiliency against provider outages, SEC rate limits, partial batch failures, and network disconnects.

---

## 4. Immediate Next Step

Begin **Phase 0 (Evaluation Platform v2)**:
1. Extend evaluation schemas in `packages/fdre/fdre/evals/datasets.py` for task stratification and gold-quote metadata.
2. Build validation and evaluation commands to establish the frozen baseline.
