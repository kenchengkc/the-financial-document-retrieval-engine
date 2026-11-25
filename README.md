# Financial Document Retrieval Engine

FDRE lets you search and compare the annual and quarterly reports companies file with the SEC
(10-Ks and 10-Qs). [Open the research panel](https://thefdre.com)

## Using the research panel

- **Ask** a question and read the filing passages cited in the answer. If there's too little
  evidence, Ask says so.
- **Retrieve** a passage by company, date, or filing section. This tab also lets you compare
  filings, look up financial figures, and export data as CSV, JSON, or Parquet.
- **Screen** companies by topic. Try `data center construction` to see which companies discuss
  it, what they said, and when they filed.
- **Signals** shows how stocks performed after a filing. Open a saved study to check its data
  and assumptions.

The **as-of date** limits a search to filings the SEC had accepted by then. A March quarterly
report filed in May won't appear in an April search. If you're studying the S&P 500 in a past
year, check which companies belonged to it then. Some have since left the index.
[Historical membership guide](docs/research/historical_universe.md)

## Run the local demo

You'll need Python 3.11 or later, uv 0.12.10, Node.js 22, and Docker with Compose. The demo
loads one fictional annual report and runs without API keys.

From the top of a fresh checkout, start the database, load the sample filing, and run the API.

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
`subscription demand`. The `EXMPL` filing says, “Revenue increased because subscription demand
grew.” You can try the same search with `POST /search` in the
[local API docs](http://localhost:8000/docs).

## Architecture

FDRE downloads filings and reported figures from the SEC and stores them in PostgreSQL. It
splits the filing text into passages and keeps each passage with its section and source link.
Tables keep their rows and column headings, so you can tell which year a figure belongs to.
When you update the index, the importer skips filings it has already processed.

Search applies your company and date filters before ranking the passages. It looks for the
words you typed and uses pgvector to match passages by meaning. A search for
`equipment spending` can turn up a passage about buying machinery.

Before Ask returns an answer, it checks that each claim cites evidence the search found and
compares the quoted words with the source text. If a citation fails either check, Ask reports
that it couldn't verify the answer. FastAPI sends the result to the Next.js web app.
[Architecture guide](docs/architecture/system.md)

Before downloading SEC filings, put your name and contact email in `SEC_USER_AGENT` in `.env`.
Each paid indexing run needs your approval. If you use a paid search provider, it may also
charge for individual searches. [Cost policy](docs/operations/cost_budget.md)

## Research results

Reviewers marked the passages that answered each of 40 test questions. On average, 37.5% of
those passages appeared in the first ten results. The target is 85%. [Search benchmarks](docs/evaluations/eval_results.md#retrieval-benchmark)

One study asked whether changes in a company's risk disclosures could predict stock returns.
Too few later prices were available to settle the question.
[Study results](docs/evaluations/eval_results.md)

## Working with the code

Run `uv run python -m scripts.pipelines.retrieval_pipeline --help` to list commands for
indexing filings, importing financial figures, and exporting datasets. The
[contributor guide](CONTRIBUTING.md) lists the test commands and data rules.

The [documentation index](docs/README.md) lists the research guides. To check a saved study
without connecting to the database, follow the [experiment guide](docs/research/experiment-bundles.md).
