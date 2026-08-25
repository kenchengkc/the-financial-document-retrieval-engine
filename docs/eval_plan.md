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

## Cross-Sectional v2 Evidence Protocol

`data/evals/cross_sectional_benchmark.v1.jsonl` remains the immutable Part-5 issuer-ranking
baseline. Its evidence labels were inherited from older retrieval questions and therefore do not
represent the exact latest 10-Q selected by the screen in most cases. Do not rewrite v1 to repair
that historical baseline.

Part 7 starts a new development seed at
`data/evals/cross_sectional_benchmark.v2.dev.jsonl`. A v2 evidence label is eligible only when:

1. the gold issuer is resolved inside the case's frozen five-issuer universe;
2. the exact filing is selected point-in-time using the screen's `as_of`, form, and amendment
   policy;
3. `metadata.selected_accession` records that exact filing;
4. every reviewed evidence quote is a substring of a chunk from that accession and carries the
   gold ticker;
5. the benchmark case stores direct evidence instead of hydrating evidence from its historical
   source question.

The provider-free review helper prioritizes passages from the selected filing without mutating the
benchmark:

```bash
FDRE_ALLOW_PROD=1 python3 -m scripts.build_cross_sectional_evidence_review \
  data/evals/cross_sectional_benchmark.v1.jsonl \
  --split development
```

Candidate ranking in that helper is only reviewer triage; it is not a gold-label generator.
Cases whose original disclosure is absent from the selected filing must be replaced or rewritten
as new reviewed cases rather than force-labeled.

The six v1 cross-sectional holdout cases were accessed during the Part-7.1 evidence-alignment
diagnostic. They are therefore **diagnostic only** for future work and must not be presented as an
untouched OOS set. Cross-Sectional v2 will receive a new sealed holdout after the development task
mix is finalized.

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
