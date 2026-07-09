# Retrieval Benchmark

The reviewed 120-question dataset is committed at `data/evals/retrieval_benchmark.jsonl`.
Measured results and gate status live in [`docs/eval_results.md`](eval_results.md).

## Dataset Contract

- 120 human-reviewed questions: 80 development and 40 untouched holdout.
- Narrative, table, legal, guidance, temporal, cross-sectional, filter, and abstention categories.
- Reviewer identity and explicit abstention labels on every question.
- Stable evidence labels based on accession, section, normalized quotation, and content fingerprint.

Run a reviewed dataset with:

```bash
FDRE_ALLOW_PROD=1 python3 -m scripts.retrieval_pipeline eval \
  data/evals/retrieval_benchmark.jsonl \
  --require-reviewed --split holdout --k 10
```

## Release Gates

| Metric | Target | Status (2026-07-09) |
| --- | ---: | --- |
| Recall@10 | >= 0.85 | Open — Hybrid holdout **0.375** (needs human paraphrases) |
| Table Recall@10 | >= 0.80 | Open — Hybrid **0.500** |
| Citation validity | 1.00 | Not claimed from this freeze |
| Abstention macro-F1 | >= 0.85 | Open on this freeze |
| Entity-resolution accuracy | >= 0.99 | Below gate on holdout |
| Single-company search p95 | < 2.5 s | **Pass** (1.95 s) |
| Cross-sectional search p95 | < 5 s | **Pass** (1.74 s) |
| ANN Recall@10 delta from exact | <= 0.02 | **Pass** (max delta 0.00) |

Generated questions and development results must not be reported as holdout performance.
The 33-query content-grounded ablation in the README remains the primary retrieval-quality
signal until holdout labels are human-paraphrased.
