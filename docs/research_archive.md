# HU-4 Research Archive

HU-4 extends the historically reconstructed S&P 500 filing history without multiplying FDRE's
vector corpus. The archive is an issuer-level source and feature store; research eligibility still
comes from the point-in-time security universe.

## Archive contract

The production path is deliberately separate from retrieval ingestion:

```text
overlapping historical membership
        -> stable issuer CIK
        -> complete SEC submissions history
        -> 10-K accession + acceptance/availability timestamp
        -> primary filing SHA-256
        -> Risk Factors elements only
        -> risk-change feature + exact accession lineage
        -> compressed Parquet batch artifact
```

It never invokes chunking, embedding, reranking, or generation. Every apply compares the archive
embedding count before and after and fails if it changes. Historical-only issuers may have no
present-day ticker; archive selection and panel construction therefore use SEC CIKs. A missing
acceptance timestamp falls back to the end of the SEC filing date, not the beginning, so the
fallback cannot make the filing appear available earlier that day.

The filing parser terminates `Risk Factors` at any subsequent SEC item heading, including item
headings for which FDRE computes no feature. This prevents later filing sections from being
silently mislabeled as Item 1A.

## Bounded production workflow

The existing **S&P 500 batch ingestion** workflow has two modes, preserving the seven-workflow
operational surface. A blank `archive_spec` selects current-vector ingestion; a value such as
`2010-01-01:2026-09-01:false` selects the HU-4 window and provisional-cache policy:

- `current_vector`: the existing current-constituent parse/chunk/embed path;
- `research_archive`: the HU-4 annual-filing path.

Archive runs are explicitly dispatched with a filing window, issuer offset, issuer limit, and
lane. Batches are resumable and idempotent. They use the existing PostgreSQL advisory-lock lanes,
commit after each issuer/document, upload a JSON measurement report and Parquet feature artifact,
and can self-chain over a declared range. The default archive starts at `2010-01-01` and includes
issuers with verified or provisional overlapping membership evidence; this affects what data is
cached, not research eligibility. Strict downstream studies must still fail closed on provisional
membership or identity evidence.

Local read-only plan:

```bash
python -m scripts.research_archive \
  --from 2010-01-01 \
  --to 2026-09-01 \
  --offset 0 \
  --limit 10
```

Explicit apply:

```bash
python -m scripts.research_archive \
  --from 2010-01-01 \
  --to 2026-09-01 \
  --offset 0 \
  --limit 10 \
  --apply
```

## Market-outcome reproducibility

Signal and flagship workflows now emit a deterministic market-cache manifest alongside every
research artifact. Each recognized cache file records provider, symbol, requested window, actual
bar range/count, byte size, and SHA-256. The manifest has its own content hash and can be verified
without a network call:

```bash
python -m scripts.market_cache_manifest \
  --cache-dir data/cache/market \
  --manifest data/processed/market-cache/manifest.json \
  --verify
```

Cache corruption, missing files, added files, or provider-payload changes fail verification.

## Cost and promotion gate

HU-4 adds no recurring service and makes no paid model calls. It uses the existing PostgreSQL,
GitHub Actions, and SEC endpoints. This keeps incremental provider cost at `$0`; database storage
and batch runtime must still be measured from actual apply reports before the full cohort is
chained.

The production dry-run on 2026-09-01 selected historical-only issuers by CIK as intended. The
first five-issuer cohort already contained 15 parsed/vectorized filings, about 7.2 million stored
text characters, 17,967 chunks, and 17,967 embeddings. The HU-4 path reuses those rows and adds
only missing older annual filing metadata and scoped elements. This is a baseline, not a projected
whole-archive size claim.

Do not mark HU-4 complete until production reports establish:

1. full reconstructed-issuer batch coverage for the target window;
2. accession and availability completeness;
3. Risk Factors parse coverage and exact feature lineage;
4. Parquet replay identity;
5. market-cache manifest coverage for the unchanged HU-5 horizons;
6. measured storage/runtime and zero embedding growth;
7. continued normal monthly spend within `$10-15` and below the `$20` ceiling.
