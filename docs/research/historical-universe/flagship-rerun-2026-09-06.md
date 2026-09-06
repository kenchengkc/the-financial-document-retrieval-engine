# HU-5 flagship rerun — 2026-09-06

Status: **frozen `INSUFFICIENT` result under the unchanged precommitted methodology**.

This record preserves the first flagship rerun after HU-5 production identity closure. It is not a
signal rejection, promotion, or partial backtest. The sealed study failed closed before security-level
outcomes or walk-forward folds were evaluated because one issuer-level SEC filing can map to more
than one simultaneously active listed security.

## Frozen execution

| Field | Value |
| --- | --- |
| GitHub Actions run | `34003895773` |
| Workflow | `flagship-risk-churn-acceleration.yml` |
| Trigger | `workflow_dispatch` |
| Code SHA | `a969eb3b6e8d246831047b5dd9a103de607d404f` |
| `max_tickers` | `250` |
| `min_documents` | `6` |
| `max_uncached_market_fetches` | `300` |
| Artifact | `9980361918` (`flagship-risk-churn-acceleration-34003895773`) |
| Artifact SHA-256 | `a2a2ba816d5e6a4bbf9652c0cf0832313ce8d8c5375869b7cf4cdc8fa7647997` |
| Artifact retention | through 2026-12-05 |
| Result | `PRIMARY_RESULT=INSUFFICIENT` |
| Reason code | `ambiguous_security_mapping` |
| Experiment / insufficiency manifest ID | `72cab4ff9226b1d78bf721fd3f3ee81a14cf485b16b8686f8e6bd1c11f02cc68` |

The workflow itself completed successfully. Workflow success only means that the sealed pipeline
executed and persisted its fail-closed result; it does not imply alpha validation.

## Historical-universe gate

The production identity closure remained intact during the rerun:

| Gate field | Value |
| --- | --- |
| Universe | `sp500` |
| Window | 2010-01-01 through 2026-09-01 |
| Days | `6088` |
| Strict eligible days | `6088` |
| Invalid days | `0` |
| Membership blocked days | `0` |
| Membership blockers | `0` |
| Latent identity blockers | `0` |
| Gate manifest ID | `95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8` |
| Input provenance ID | `0662048623bc4a3dc0572ee56a3896de3d2ae6aea0ddaa34227bdd755e27c256` |
| Blocker audit ID | `a533626563f37aa2976b48383505944dc424af005be34761b9a982dcb2885b9b` |

The event-universe export contains `3982` resolved filing/security lineage rows and has universe
lineage ID `598908cce0946891a91ae8cf8ab5ca14c19bd5f64c350fa3bcbd8e965822cf3b`.

## Fail-closed blocker

The frozen reason is:

> At least one otherwise eligible issuer-level filing maps to multiple active securities or lacks
> stable CIK lineage; HU-5 will not guess a share class.

There are exactly **14** ambiguous accessions, all sharing issuer CIK prefix `0001652044`:

- `0001652044-18-000007`
- `0001652044-19-000004`
- `0001652044-20-000008`
- `0001652044-21-000010`
- `0001652044-22-000019`
- `0001652044-23-000016`
- `0001652044-24-000022`
- `0001652044-25-000014`
- `0001652044-25-000043`
- `0001652044-25-000062`
- `0001652044-25-000091`
- `0001652044-26-000018`
- `0001652044-26-000048`
- `0001652044-26-000071`

This is a distinct contract from HU-5 daily membership/identity validity. The historical-universe
model intentionally preserves simultaneous share classes as distinct securities beneath a common
SEC issuer/CIK. `resolve_hu5_events()` intentionally requires exactly one active security match for
an issuer-level filing and marks any multi-match event ambiguous. Unit coverage explicitly freezes
that behavior in `test_event_share_class_ambiguity_fails_closed`.

## What was not measured

Because the ambiguity gate occurs before security-level market outcomes and walk-forward scoring,
the frozen result reports:

- scored events: `0`;
- eligible walk-forward folds: `0`;
- OOS events: `0`;
- primary `1:63` observations: `0`;
- sector slices: `0`.

Therefore this run supplies **no evidence for `PROMOTE` or `REJECT`**. It supersedes the prior
`INSUFFICIENT_NOT_YET_REALIZED` state as the latest flagship execution, but it does not supersede
or reinterpret any previously measured diagnostic returns.

## Methodology preservation

No post-result share-class selection is permitted under this frozen run. In particular, do not:

- pick one active share class because it is the current or more familiar ticker;
- duplicate one issuer filing into every active share class without an explicit observation-weight
  policy;
- silently drop multi-class issuers from the sample; or
- construct an issuer-level return basket after seeing the study result.

Any future treatment of issuer filings with multiple simultaneously active securities is a
**methodological amendment**, not a bug fix to this result. It must be specified and versioned before
another return evaluation. The amendment must define the research observation unit, PIT-safe
security selection or aggregation rule, weighting, provenance, and how correlated share classes
affect cross-sectional inference.

Until that amendment is frozen, the canonical HU-5 flagship conclusion is **`INSUFFICIENT` due to
`ambiguous_security_mapping`**.
