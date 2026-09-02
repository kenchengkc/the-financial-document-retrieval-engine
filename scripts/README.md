# Operational scripts

The `scripts` package contains executable entry points only. Reusable business logic belongs under
`src/fdre` or the application packages.

## Layout

- `benchmarks/` — retrieval, answer, latency, ANN, and cross-sectional evaluation tooling.
- `ingestion/` — SEC ingestion, catalog construction, repair, and operational maintenance.
- `pipelines/` — top-level orchestration commands that compose multiple FDRE subsystems.
- `research/` — reproducible research, experiment, market-cache, and reporting commands.
- `research/historical_universe/` — Historical Universe construction, audits, evidence, and gates.
- `maintenance/` — repository and developer-maintenance checks.

Run scripts as modules from the repository root so package imports are deterministic, for example:

```bash
python -m scripts.pipelines.retrieval_pipeline audit
python -m scripts.ingestion.ingest_ticker_batch --help
python -m scripts.research.historical_universe.universe_snapshot --help
```

Do not add new Python entry points directly under `scripts/`; place them in the appropriate domain
folder instead.
