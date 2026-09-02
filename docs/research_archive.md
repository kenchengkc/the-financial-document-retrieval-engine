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

The subsequent bounded apply used the first three of 822 eligible issuer CIKs. It completed in
2 minutes 28 seconds including runner setup and the production data-quality audit; archive
materialization itself took 42.2 seconds. The run selected 34 annual filings, protected 10 existing
filings, downloaded and parsed 24 missing filings (53,441,013 transfer bytes), and retained 3,120
Risk Factors elements containing 1,306,013 text bytes. It exported 32 feature rows with complete
accession and availability fields and no future lineage. One historical-only issuer in the cohort
had no selected 10-K in the SEC window, which is recorded rather than substituted with another
identity. Scoped chunk and embedding counts remained exactly 10,696 before and after. Paid
embedding, reranking, and generation calls and estimated provider cost were all zero. The source
artifact is GitHub Actions run `33561265364`.

## Full production result

The measured full archive cohort contains 822 unique issuer CIKs with verified or provisional
overlapping membership evidence (785 have at least one verified membership). Production ran from
2026-09-01 21:36 UTC through 2026-09-02 03:02 UTC in 33 disjoint, resumable batches. Two lanes were
capped at five SEC requests per second each, preserving the SEC-wide ten-request-per-second
ceiling. One batch stopped on a missing SEC submissions root; the fix was merged in PR #68 and the
same offset resumed idempotently. No later issuer was skipped.

Aggregating every batch report produced:

- 11,166 selected 10-K records across all 822 CIKs, with no duplicate cohort assignment;
- 9,728 new document rows and 1,438 evidence-backed updates;
- 10,008 filings downloaded and parsed, transferring 43,072,314,555 bytes from SEC;
- 590 filings explicitly recorded without a selected Risk Factors section;
- 1,509,402 retained elements and 654,447,650 incremental text bytes;
- 10,681 Parquet feature rows across 807 CIKs in 3,249,996 artifact bytes;
- exactly one unavailable SEC submissions root, CIK `0000076406`, retained as a named gap;
- zero new chunks, zero new embeddings, zero paid model calls, and zero new recurring services.

Independent replay loaded and verified all 33 Parquet artifacts. All 10,681 rows had an accession
and availability timestamp, no feature lineage exceeded its event availability, and every batch
snapshot verified. The final scoped corpus contains 11,166 documents, 10,576 parsed documents,
3,229,381 elements, 1,365,146,178 text bytes, and the unchanged 1,677,521 pre-existing
chunks/embeddings. Summed materialization time was 28,412,796 ms across both lanes; end-to-end wall
time was about 5 hours 26 minutes including the stopped batch and hotfix promotion.

HU-4's archive, lineage, Parquet, storage, runtime, and cost gates are complete. The market-cache
manifest machinery is implemented and corruption-tested. HU-5 must still populate and verify the
actual historical-symbol outcome cache for its unchanged `1:21`, `1:63`, and `1:126` horizons;
missing outcome coverage remains a fail-closed HU-5 result, not a reason to alter the archive or
silently narrow the reconstructed universe.
