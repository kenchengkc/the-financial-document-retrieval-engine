# Retrieval telemetry

`GET /operations/retrieval-telemetry` exposes aggregate operational telemetry from already-persisted retrieval and answer runs without returning user content.

## Sampling contract

The endpoint selects the newest persisted rows independently from `retrieval_runs` and `answer_runs`, up to `sample_limit` rows from each table. The default is 1,000 rows per run type; callers may request 50–5,000.

These are therefore **two independent latest-N samples**. They are not an all-request metric, a fixed time window, or an SLO window. `earliest_observed_at` and `latest_observed_at` describe the union of the rows that happened to be selected, not a requested observation interval.

## Returned metrics

The response includes retrieval latency p50/p95/mean/min/max, the same latency distribution by retriever variant, answer latency p50/p95, answer abstention rate, mean answer confidence, observed sample sizes, and UTC observation timestamps.

Percentiles use nearest-rank calculation over the bounded persisted sample. Metrics describe only runs with a persisted `latency_ms` value.

## Privacy boundary

The telemetry SQL projection intentionally selects only numeric/boolean telemetry, retriever variant, and timestamps. It does not select or return:

- retrieval query text;
- retrieval filters;
- answer questions or answer text;
- abstention reasons;
- answer trace payloads;
- citation text or individual run identifiers.

Tests assert both response-level absence of planted private values and SQL-level absence of those sensitive columns from the telemetry queries.

## Interpretation

Use this endpoint to spot broad latency regressions, retriever-variant differences, and changes in fail-closed behavior. Do not use it as a substitute for a time-series observability system or to make availability/SLO claims.

The design is intentionally database-backed and bounded so production observability improves without adding another recurring service or violating the repository's operating-cost budget.
