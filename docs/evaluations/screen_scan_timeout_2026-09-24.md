# Screen scan timeout investigation

## Failure and fix

Production revision `1624b45d33c05359b2b0266b336e71e4326be4aa` returned an
unhandled database statement timeout for the Screen theme `data center constructions`.
The failing statement selected embedding IDs with `ORDER BY distance, chunk_id`.
Production `EXPLAIN` showed a parallel sequential scan and sort over the embedding
corpus. The existing `ix_embeddings_voyage_512_hnsw` index was present but could not
serve that ordering. A repeat HTTP request succeeded in 20.803 seconds.

Candidate selection now orders only by cosine distance so PostgreSQL can use the
HNSW index. The bounded hydration query retains its distance/ID ordering and all
existing document, issuer, and point-in-time filters. The unfiltered search uses
`hnsw.ef_search = 1000`; hydration remains limited to the existing 3x candidate pool.
Filtered search settings are unchanged.

The thematic endpoint also translates SQLSTATE `57014` into a handled HTTP 503 with
a public timeout message. This response passes through CORS, so the browser can
display the cause instead of reporting an unreachable service. Other database
errors still propagate; no SQL or database details are returned to the browser.

## Bounded development comparison

Measured September 24, 2026 UTC against production data in read-only transactions.
Each theme used the same Voyage query vector for both implementations. The sample
contains the reported theme and all five `CROSS_SECTIONAL_QUERIES` from
`scripts/benchmarks/benchmark_latency.py`, with an unfiltered dense limit of 50.
No historical holdout was used.

| Theme | Previous query, warm (ms) | Indexed query, ef=1000 (ms) | Top-10 overlap | Top-50 overlap |
| --- | ---: | ---: | ---: | ---: |
| data center constructions | 2193 | 3640 | 100% | 100% |
| data center power constraints | 2146 | 2605 | 100% | 100% |
| artificial intelligence regulation risk | 2386 | 1425 | 100% | 100% |
| cybersecurity incident response | 2115 | 1417 | 100% | 100% |
| supply chain concentration risk | 2124 | 1803 | 100% | 100% |
| interest rate sensitivity | 2362 | 2304 | 100% | 100% |

These are single dense-search measurements including local-to-database network
latency, not end-to-end percentiles. An earlier pass of the previous query timed
out after 25 seconds for the reported theme and took 20.121 seconds for the data
center power theme. Warm full scans are much faster, so their timings above do not
represent the failure's cold-read conditions.

Search depths of 150 and 400 were also checked. Both missed four of the exact
top-ten passages for the supply-chain theme; 1000 recovered the exact top-ten and
top-fifty sets across this small sample. This development check is not a general
recall guarantee for every theme or corpus revision.

A browser check used the production Screen UI with only its thematic request
redirected to the corrected local API, backed by production data. The exact user
query returned HTTP 200 and three issuer cards (LITE, AMT, CEG), with no error
notice: 3246 ms request wall time and 3106 ms API-reported retrieval time. This
verifies the proposed implementation, not a production deployment.

To reproduce, obtain one query embedding per theme, run the previous and updated
`DenseRetriever.search_with_vector` with `SearchFilters()` and `limit=50` in
separate read-only transactions, and compare returned chunk-ID sets at 10 and 50.
Use `EXPLAIN` on the actual embedding-ID statement to confirm HNSW eligibility.
Unit and integration tests use synthetic vectors and no paid provider calls.

## Regression coverage and cost

The PostgreSQL index test now captures and explains the actual application query,
rather than a separately handwritten query. Its synthetic corpus exceeds the
default HNSW search depth and checks index eligibility, candidate count, and result
ordering. Mutations restoring the secondary sort or reducing search depth to 40
both fail the test. API tests check the timeout status, CORS header, safe message,
and propagation of unrelated database failures.

No new service, index, provider call, or recurring infrastructure is added. The
larger bounded ANN search costs more than an ANN search at depth 40, but avoids the
unbounded corpus scan that caused the timeout.
