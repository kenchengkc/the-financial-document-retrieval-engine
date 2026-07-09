# Evaluation Results

Measured on production Neon on 2026-07-09 after latency, ANN, and label-refinement
work. Reports under `data/processed/evals/` are local artifacts and are not committed.

## Corpus at measurement

| Metric | Value |
| --- | ---: |
| Documents | 2,761 |
| Chunks / embeddings | ~2.71M |
| Embedding model | Voyage `voyage-4-large`, 512-d `halfvec` |
| S&P 500 indexed | 498 / 499 |
| Documents without chunks | **0** |
| FDXF | **Blocked** — SEC CIK `0002082247` has Form 3/4/8-K only; no 10-K/10-Q yet |

## Dataset freeze

`data/evals/retrieval_benchmark.jsonl` is a reviewed **120-question** contract
(80 development / 40 holdout, all eight categories, `reviewed_by` stamped).
Evidence quotes were re-grounded onto stored chunks
(`scripts/reground_benchmark_evidence.py`). Prior 33-query ablation set kept at
`data/evals/retrieval_benchmark.pre120.jsonl`.

## Holdout retrieval (`--split holdout --k 10`)

| Variant | Recall@10 | MRR | Table Recall@10 |
| --- | ---: | ---: | ---: |
| Dense only | 0.350 | 0.192 | 0.500 |
| Sparse only | 0.250 | 0.068 | 0.000 |
| **Hybrid** | **0.375** | **0.164** | **0.500** |

Lift from first freeze (Hybrid Recall@10 **0.050 → 0.375**). Still below the
aspirational ≥ 0.85 gate — remaining gap needs **human-authored** paraphrases.
Do not market holdout scores as production-ready quality. Primary quality signal
remains the 33-query content-grounded ablation.

## Latency (stratified)

`python3 -m scripts.benchmark_latency` (`k=10`, warmup=2, repeats=2):

| Workload | p50 | p95 | Gate | Pass |
| --- | ---: | ---: | ---: | --- |
| Single-name | 723 ms | **1,950 ms** | < 2,500 | **yes** |
| Cross-sectional | 1,592 ms | **1,736 ms** | < 5,000 | **yes** |

Cross-sectional improved from ~59 s p95 → **1.7 s** via: skip finance expansion
when unfiltered, batch Voyage embeds, dense-only unfiltered hybrid, smaller
candidate pools, ANN-first unfiltered path, capped sparse tokens, thematic
`top_k` reduction.

## Exact-versus-ANN Recall@10

| Metric | Value | Gate | Pass |
| --- | ---: | ---: | --- |
| Mean ANN Recall@10 | **1.00** | — | — |
| Max delta from exact | **0.00** | ≤ 0.02 | **yes** |

`hnsw.ef_search=400` on filtered issuer searches.

## Ablation continuity (33 content-grounded queries)

| Variant | recall@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: |
| Baseline | 0.152 | 0.086 | 0.102 |
| **Shipped multi-query** | **0.212** | **0.134** | **0.153** |
| + neighbor expansion | 0.242 | — | — |

## Reproduce

```bash
export FDRE_ALLOW_PROD=1
export PYTHONPATH=packages/fdre:.

python3 -m scripts.benchmark_latency --k 10 --warmup 2 --repeats 2
python3 -m scripts.benchmark_ann_recall --k 10
python3 -m scripts.retrieval_pipeline eval data/evals/retrieval_benchmark.jsonl \
  --require-reviewed --split holdout --k 10
```
