# Neon Launch migration (S&P 500 indexing)

FDRE production can use **Neon Launch** (pay-as-you-go Postgres with pgvector) instead of
Railway Postgres. Railway Free caps volume at **0.5 GB** with no resize; Neon Launch bills
storage at **$0.35/GB-month** and supports pgvector on all plans.

This guide sets up Neon for **S&P 500 batch ingestion** while keeping the API on Railway and
the frontend on Vercel.

## Architecture after migration

| Component | Host | Database connection |
|-----------|------|---------------------|
| API (`api.thefdre.com`) | Railway | Neon **pooled** URL |
| GitHub ingest workflows | GitHub Actions | Neon **direct** URL |
| Frontend (`thefdre.com`) | Vercel | N/A (calls API only) |

Use two connection strings from Neon:

- **Pooled** (`…-pooler…`) — many short API requests
- **Direct** (no `-pooler`, port 5432) — Alembic and long ingest/embed jobs

## 1. Create Neon Launch project

1. Sign up at [neon.tech](https://neon.tech) and upgrade the org to **Launch** (Billing → add a payment method; you pay for usage, not a flat $25).
2. **New project** → Postgres 16 → region close to Railway API (e.g. `us-east-2`).
3. Create database `fdre` (or use `neondb`).
4. In **Connect**:
   - Copy **pooled** connection string → `DATABASE_URL` (API + GitHub fallback)
   - Copy **direct** connection string → `DATABASE_URL_DIRECT` (ingest only)
5. In **SQL Editor**, enable vectors:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 2. Initialize schema

From your laptop, using the **direct** URL:

```bash
export DATABASE_URL="postgresql://USER:PASS@ep-xxx.us-east-2.aws.neon.tech/fdre?sslmode=require"
alembic upgrade head
```

FDRE normalizes `postgresql://` to `postgresql+psycopg://` automatically.

Smoke test:

```bash
EMBEDDING_PROVIDER=local_hash python -m scripts.retrieval_pipeline seed-demo
curl http://127.0.0.1:8000/coverage   # with API pointed at Neon locally
```

## 3. Migrate data from Railway (optional)

If Railway Postgres is still readable, dump and restore:

```bash
pg_dump "$RAILWAY_DATABASE_PUBLIC_URL" --no-owner --no-acl -Fc -f fdre.dump
pg_restore -d "$NEON_DIRECT_URL" --no-owner --no-acl --clean --if-exists fdre.dump
```

If Railway is full or crash-looping, **skip the dump** and re-ingest on Neon (step 5).

## 4. Update production secrets

### GitHub (Settings → Secrets and variables → Actions)

| Secret | Value |
|--------|--------|
| `DATABASE_URL` | Neon **pooled** connection string |
| `DATABASE_URL_DIRECT` | Neon **direct** connection string |
| `SEC_USER_AGENT` | unchanged |
| `VOYAGE_API_KEY` | unchanged (if using Voyage) |

Ingest workflows prefer `DATABASE_URL_DIRECT` when set.

### Railway API service (Variables)

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | Neon **pooled** connection string |

Redeploy the API service after changing `DATABASE_URL`.

You can **remove or stop** the Railway Postgres service once Neon is verified.

## 5. S&P 500 ingest plan on Neon

Current partial state (from Railway): ~29 companies, ~31k embedded chunks. After a fresh
Neon schema or restore, resume with small batches.

**Batch size:** use `limit=10` per workflow run (~1–2 GB growth rate depends on filings and
chunk count). Increase Neon storage in the dashboard as usage grows.

### Finish batch 0 (if data was restored)

GitHub Actions → **S&P 500 batch ingestion**:

- `offset`: `0`
- `limit`: `10`
- `filing_limit`: `1`

Re-running index-only locally for tickers that have chunks but missing embeddings:

```bash
export DATABASE_URL="$NEON_DIRECT_URL"
python -m scripts.retrieval_pipeline index --tickers A AAPL ABBV ...
```

Only run **one** ingest workflow at a time. Megacap and S&P 500 jobs share the `fdre-ingestion`
concurrency group so they queue instead of racing on the same tickers.

To walk the full list automatically, trigger **S&P 500 batch ingestion** once with `chain=true`;
each successful batch queues the next `offset + limit`. Do not fire dozens of dispatches at
once — GitHub cancels duplicate pending runs.

### Walk the full S&P 500

Advance `offset` by `limit` after each successful run:

| Run | offset | limit | Tickers (approx.) |
|-----|--------|-------|-------------------|
| 0 | 0 | 10 | A … ADSK |
| 1 | 10 | 10 | … |
| … | +10 | 10 | … |
| 49 | 490 | 10 | last names |

499 primary tickers in `data/sample/sp500_tickers.json` → ~50 runs at `limit=10`.

### Local batch (same as CI)

```bash
export DATABASE_URL="$NEON_DIRECT_URL"
export SEC_USER_AGENT="FDRE your-email@example.com"
python scripts/ingest_ticker_batch.py --universe sp500 --offset 0 --limit 10
```

## 6. Verify

```bash
curl https://api.thefdre.com/health
curl https://api.thefdre.com/coverage
```

Coverage badge on [thefdre.com](https://thefdre.com) should reflect new `indexed_count`.

## 7. Storage and cost (rough)

| Scale | Embedded chunks (est.) | Neon storage (est.) | Monthly storage cost |
|-------|------------------------|---------------------|----------------------|
| Megacap (5) | ~8k | ~0.3 GB | ~$0.10 |
| S&P 500 batch 0–50 (partial) | ~30k | ~1 GB | ~$0.35 |
| Full S&P 500 (1 filing each) | ~400k+ | ~10–20 GB | ~$3.50–7 |

Monitor usage in Neon **Billing** → set a spending alert on Launch.

### Storage limit errors (`512 MB` / `DiskFull`)

Neon projects start with a **512 MB data size limit** until you raise it. Full S&P 500 indexing
needs **several GB**. When embed fails with `project size limit (512 MB) has been exceeded`:

1. Neon console → your project → **Settings** → increase **Data size limit** (Launch: set to
   **5–10 GB** to start, raise as ingest grows).
2. Wait for the project to become writable again.
3. **Resume embeddings only** for the failed batch (chunks already exist):

```bash
DATABASE_URL="$DATABASE_URL_DIRECT" python scripts/ingest_ticker_batch.py \
  --universe sp500 --offset 40 --limit 10 --index-only
```

Or GitHub Actions → **S&P 500 batch ingestion** with the same `offset`/`limit` and
`index_only=true`. Do **not** enable `chain` until storage headroom is confirmed.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `DiskFull` / storage suspended | Upgrade Neon storage or delete old data; use smaller `limit` |
| Ingest times out on pooled URL | Set `DATABASE_URL_DIRECT` secret to Neon direct host |
| `extension "vector" does not exist` | Run `CREATE EXTENSION vector;` in SQL Editor |
| Cold start latency on API | Neon scales to zero after 5 min; first request may be ~1–2s |
| GOOGL vs GOOG in S&P count | Catalog primary is `GOOG`; both tickers map to same CIK |
