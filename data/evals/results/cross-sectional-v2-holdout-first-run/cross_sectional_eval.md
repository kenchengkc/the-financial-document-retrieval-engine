# FDRE Cross-Sectional Evaluation

## Run Metadata

- **benchmark_name:** `cross_sectional_benchmark.v2.holdout`
- **chunk_count:** `3039403`
- **corpus_snapshot_id:** `388fe80d07d5bd6e`
- **dataset:** `data/evals/cross_sectional_benchmark.v2.holdout.jsonl`
- **dataset_sha256:** `9bb4736ab5e7373be6edcdac05ac781398b3a77f00b0d2dfdd5be6187d9deccc`
- **document_count:** `3204`
- **embedding_count:** `3039403`
- **embedding_dimensions:** `512`
- **embedding_model:** `voyage-4-large`
- **embedding_provider:** `voyage`
- **evaluated_subset_sha256:** `9bb4736ab5e7373be6edcdac05ac781398b3a77f00b0d2dfdd5be6187d9deccc`
- **feature_version:** `fdre-panel-v3`
- **generated_at:** `2026-08-26T06:01:59.086448+00:00`
- **git_sha:** `ee80bae16d5f4d605db7ed15770c5158e79324bc`
- **hydrated_dataset_sha256:** `9bb4736ab5e7373be6edcdac05ac781398b3a77f00b0d2dfdd5be6187d9deccc`
- **issuer_ks:** `[1, 3, 5]`
- **min_rerank_score:** `0.0`
- **question_count:** `14`
- **rerank_top_n:** `50`
- **reranker_model:** `rerank-2.5`
- **reranker_provider:** `none`
- **result_limits:** `[5]`
- **screen_retrieval_path:** `hybrid+none`
- **semantic_candidate_limits:** `[50]`
- **source_dataset:** `data/evals/retrieval_benchmark.jsonl`
- **source_dataset_sha256:** `ed01d5c7a6ec52056af197d9034dcc87acaad5ecf8828b163f6cd934e6d397d5`
- **split:** `holdout`
- **task_type_counts:** `{"change_screen": 2, "semantic_screen": 5, "semantic_structured_screen": 3, "structured_screen": 3, "temporal_screen": 1}`

## Overall

Questions: **14**

| Metric | @1 | @3 | @5 |
| --- | ---: | ---: | ---: |
| Issuer Recall | 1.000 | 1.000 | 1.000 |
| Issuer Precision | 1.000 | 0.333 | 0.200 |
| Evidence Recall | 0.778 | 0.778 | 0.778 |

- Condition grounding: **0.000%** across **8** reviewed-condition questions
- PIT leakage: **0.000%**
- Zero-result accuracy: **n/a**
- Mean max-issuer evidence share: **0.353**
- p50 latency: **3154.5 ms**
- p95 latency: **6145.1 ms**
- Mean semantic-search calls: **0.643**
- Max semantic-search calls: **1**

## By Task Type

| Task type | N | Issuer R@1 | Issuer R@3 | Issuer R@5 | Issuer P@1 | Issuer P@3 | Issuer P@5 | Evidence R@1 | Evidence R@3 | Evidence R@5 | Condition grounding | PIT leakage | Zero-result acc. | p95 ms | Mean semantic calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| change_screen | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | 0.200 | 0.000 | 0.000 | 0.000 | 0.000% | 0.000% | n/a | 2980.8 | 0.000 |
| semantic_screen | 5 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | 0.200 | 0.800 | 0.800 | 0.800 | n/a | 0.000% | n/a | 7326.8 | 1.000 |
| semantic_structured_screen | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | 0.200 | 0.667 | 0.667 | 0.667 | 0.000% | 0.000% | n/a | 3523.3 | 1.000 |
| structured_screen | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | 0.200 | 0.000 | 0.000 | 0.000 | 0.000% | 0.000% | n/a | 2080.8 | 0.000 |
| temporal_screen | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | 0.200 | 1.000 | 1.000 | 1.000 | n/a | 0.000% | n/a | 3820.0 | 1.000 |
