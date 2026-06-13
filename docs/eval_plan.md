# Retrieval Benchmark

The benchmark runner and dataset contract are implemented. The reviewed question set is not yet
committed or published, so FDRE does not claim holdout quality scores.

## Dataset Contract

- 120 human-reviewed questions: 80 development and 40 untouched holdout.
- Narrative, table, legal, guidance, temporal, cross-sectional, filter, and abstention categories.
- Reviewer identity and explicit abstention labels on every question.
- Stable evidence labels based on accession, section, normalized quotation, and content fingerprint.

Run a reviewed dataset with:

```bash
python3 -m scripts.retrieval_pipeline eval path/to/retrieval_benchmark.jsonl \
  --require-reviewed --split development --k 10
```

Reports record corpus snapshot, Git SHA, parser version, embedding and reranker configuration,
retrieval settings, latency, and configured provider cost.

## Release Gates

| Metric | Target |
| --- | ---: |
| Recall@10 | >= 0.85 |
| Table Recall@10 | >= 0.80 |
| Citation validity | 1.00 |
| Abstention macro-F1 | >= 0.85 |
| Entity-resolution accuracy | >= 0.99 |
| Single-company search p95 | < 2.5 s |
| Cross-sectional search p95 | < 5 s |
| ANN Recall@10 delta from exact | <= 0.02 |

Generated questions and development results must not be reported as holdout performance.
