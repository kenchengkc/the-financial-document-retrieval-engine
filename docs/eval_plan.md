# Retrieval Benchmark and Research Report

FDRE evaluates sparse, dense, hybrid, and hybrid-plus-reranker retrieval against a
reviewed 120-question dataset. Evidence labels are stable across rechunking because
they use SEC accession number, section, normalized quotation, and a content
fingerprint instead of database chunk IDs.

## Dataset contract

- 80 development questions and 40 untouched holdout questions
- narrative, table, legal, guidance, temporal, cross-sectional, filter, and
  abstention categories
- reviewer identity on every question
- stable evidence for supported questions
- explicit `should_abstain` labels for unsupported questions

Run the contract check and benchmark with:

```bash
python -m scripts.retrieval_pipeline eval data/sample/retrieval_benchmark.jsonl \
  --require-reviewed --split development --k 10
```

The JSON report records the corpus snapshot, Git SHA, parser version, embedding and
reranker configuration, question split, latency, and configured provider cost. The
Markdown report summarizes Recall@10, MRR, nDCG@10, table recall, citation
precision, abstention macro-F1, entity-resolution accuracy, p95 latency, and cost
per query.

## Release gates

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

Numbers are published only after the holdout run completes against an identified
corpus snapshot. Generated questions or development-set results are not presented
as holdout performance.
