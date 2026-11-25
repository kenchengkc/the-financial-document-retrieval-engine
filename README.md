# Financial Document Retrieval Engine

Search annual and quarterly SEC filings (10-Ks and 10-Qs), compare what companies reported,
and trace an answer back to the passage it came from. [Open the research panel](https://thefdre.com)

## Using the research panel

- **Ask** answers questions about filings and cites the passages it uses. If the filings don't
  support an answer, it says so.
- **Retrieve** finds passages by company, date, or section. You can also compare filings, look
  up reported figures, or export data as CSV, JSON, or Parquet.
- **Screen** searches for a topic across companies. Try `data center construction` to see
  matching passages alongside each company's ticker and filing date.
- **Signals** shows studies of what happened after companies filed their reports. You can check
  the data and assumptions behind a saved study.

For historical research, the **as-of date** matters. If a quarter ended in March and the SEC
accepted the filing in May, an April search excludes that filing. To find out which companies
belonged to the S&P 500 on a past date, use the historical membership records. Today's list
leaves out companies that have since left the index. [Historical membership guide](docs/research/historical_universe.md)

## Run the local demo

You'll need Python 3.11 or later, uv 0.12.10, Node.js 22, and Docker with Compose. The demo
loads one fictional annual report and runs without API keys.

In a fresh checkout, run these commands from the repository root to start the local database,
load the sample, and start the API.

```bash
cp -n .env.example .env
uv sync --frozen --extra dev --extra data
docker compose up -d --wait postgres
uv run alembic upgrade head
uv run python -m scripts.pipelines.retrieval_pipeline seed-demo
uv run uvicorn apps.api.app.main:app --reload
```

Open a second terminal in the repository root and start the web app.

```bash
cd apps/web
cp -n .env.example .env.local
npm ci
npm run dev
```

Open the [local research panel](http://localhost:3000), choose **Retrieve**, and search for
`subscription demand`. The sample filing for ticker `EXMPL` attributes its revenue growth to
subscription demand. You can try the same query through `POST /search` in the
[local API docs](http://localhost:8000/docs).

## Architecture

The importer reads SEC filings and financial figures from the SEC's Company Facts data.
PostgreSQL stores the text, figures, and search index. Search combines keyword matches with
passages that are similar in meaning, using the pgvector extension. A FastAPI service sends
results and citations to the Next.js web app. [Architecture guide](docs/architecture/system.md)

Before downloading live filings, set `SEC_USER_AGENT` in `.env` to identify yourself and give
the SEC a contact email. Paid document indexing requires approval for each run. Searches can
still incur query charges if you use a paid provider. [Cost policy](docs/operations/cost_budget.md)

## Research results

On a published set of 40 test questions, the top ten search results contained an average of
37.5% of the expected evidence. The project's target is 85%. [Search benchmarks](docs/evaluations/eval_results.md#retrieval-benchmark)

One study tested whether changes in the risks companies reported could predict returns. The
latest published run lacked enough price data after the filings to draw a conclusion.
[Study results](docs/evaluations/eval_results.md)

## Working with the code

Run `uv run python -m scripts.pipelines.retrieval_pipeline --help` to list commands for
indexing filings, importing financial figures, and exporting datasets. The
[contributor guide](CONTRIBUTING.md) lists the test commands and data rules.

For details on historical research and offline verification, see the
[documentation index](docs/README.md) and the [experiment guide](docs/research/experiment-bundles.md).
