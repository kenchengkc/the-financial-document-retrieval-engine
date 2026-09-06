# HU-5 market-provider symbology policy v1

Status: **frozen before any further amended HU-5 return evaluation**.

This policy changes only how the market-data provider is addressed. It does not change the historical-universe identity, event ticker, issuer-to-outcome mapping, signal definition, horizons, walk-forward configuration, costs, neutralization, or promotion gates.

## Invariant

The research lineage remains:

`filing -> CIK -> event-date security -> historical event ticker`

Provider addressing is a separate layer:

`historical event ticker -> evidenced provider query symbol -> market bars -> relabel bars to historical event ticker`

A provider alias must never rewrite the PIT event lineage. For example, a Ball filing observed under `BLL` remains `BLL`; Tiingo may be queried using `BALL`, but the resulting bars are keyed back to `BLL` before event-study evaluation.

## Frozen aliases

| Historical symbol | Provider symbol | Effective date | Continuity class | Evidence |
|---|---|---|---|---|
| `BLL` | `BALL` | 2022-05-10 | ticker rename | Ball Corporation: https://www.ball.com/our-company/ball-stories/ticker-symbol-changed-to-ball |
| `KFT` | `MDLZ` | 2012-10-02 | spin-off; pre-distribution event windows only | Mondelez International: https://www.mondelezinternational.com/investors/stock/spin-off-information/ |
| `MHP` | `SPGI` | 2013-05-14 | ticker-rename chain (`MHP -> MHFI -> SPGI`) | S&P Global: https://press.spglobal.com/2013-05-14-McGraw-Hill-Financial-to-Begin-NYSE-Trading-Under-New-MHFI-Stock-Symbol-on-Tuesday-May-14-at-the-Opening-Bell |
| `MHFI` | `SPGI` | 2016-04-28 | ticker rename | S&P Global: https://investor.spglobal.com/contact-investor-relations/investor-faq/ |
| `MMC` | `MRSH` | 2026-01-14 | ticker rename; CUSIP unchanged | Marsh: https://www.marsh.com/en/corp/about/news/marsh-mclennan-to-change-nyse-symbol-to-mrsh.html |
| `PKI` | `RVTY` | 2023-05-16 | ticker rename | Revvity: https://news.revvity.com/press-announcements/press-releases/press-release-details/2023/Revvity-Announces-Financial-Results-for-the-First-Quarter-of-2023/default.aspx |
| `TMK` | `GL` | 2019-08-09 | ticker rename | Globe Life: https://investors.globelifeinsurance.com/news-releases/2019/august/torchmark-corporation-has-officially-been-renamed-globe-life-inc?accessibility=true |

S&P Global explicitly states that historical prices for `MHP` and `MHFI` are available under `SPGI`.

## KFT fail-closed rule

`KFT -> MDLZ` is not treated as a generic ticker rename. Kraft Foods Inc. completed the Kraft Foods Group spin-off on 2012-10-01 and began regular-way trading as Mondelēz International under `MDLZ` on 2012-10-02.

Therefore the provider alias is permitted only when every required event-study endpoint for the `KFT` observation is strictly before **2012-10-01**. If any required endpoint reaches or crosses the distribution date, HU-5 must fail closed rather than infer a post-separation total-return continuation.

The frozen HU-5 corpus currently has one `KFT` event, dated 2012-02-27, whose longest predeclared 1:126 endpoint is 2012-08-24. Implementation must verify this from the actual benchmark-session calendar before using the alias; it must not rely only on this prose assertion.

## Hydration evidence

Hydration run `34016265578` produced artifact `9988735626`, digest `sha256:e502a69ded4ce119ce22e9ae4dbfa2238d8c9fff428d65fe916bd0348609b4e7`.

It left exactly seven historical symbols unresolved: `BLL`, `KFT`, `MHFI`, `MHP`, `MMC`, `PKI`, `TMK`, while the corresponding provider symbols were already present in the same Tiingo cache namespace for the full requested 2012-01-16 through 2027-04-19 window:

- `BALL`: `sha256:c2acdb77b02cea4873c8c9e7a892cc1ebaf9846292b07e9c41aa490190401af5`
- `MDLZ`: `sha256:e769897d7a2b1bcff0f22d2a004b147c9603ec1b929467e0c37f64fbf13c2be1`
- `SPGI`: `sha256:f2df4ea1b1b73e41583edc212373317349cb2ffacd3eb9f8f32286e76ab7d5f1`
- `MRSH`: `sha256:c17510b3f9b1eb2c299270ee2301a211a32442c4c2dbd1d6e02a6d706332dce6`
- `RVTY`: `sha256:8ef0ec1b3eb9e8a1adf1f6f5fe974f5dac7c4a89b0d9b5938149b9523fbfc6f6`
- `GL`: `sha256:e4146314de0ba42e94ee916d6a6c558353f8fd7dcfa2215dc367d1957854e68d`

This is evidence that the operational blocker is provider symbology rather than seven independent absent price histories. It is not return evidence.

## Frozen provenance payload

Implementation must produce this deterministic policy manifest identity without adding or removing aliases after return evaluation:

`market_symbology_manifest_id = 89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328`

The manifest is the SHA-256 of canonical JSON (`sort_keys=true`, separators `(',', ':')`) containing `schema_version = fdre-hu5-market-symbology-v1` and the seven alias records above, including provider, provider symbol, continuity class, effective date, event-window constraint, and evidence URL.

## Research-state invariants

Adding this provider layer must preserve all of the following exactly:

- strict historical-universe days: `6088 / 6088`
- issuer outcome policy: `fdre-hu5-multiclass-outcome-v1`
- outcome mapping ID: `17c668c61da943beb48c9f3dd58325ab7222bb3836d21774eacfa07b0f704cd2`
- resolved issuer observations: `3996`
- multi-class observations: `14`
- primary horizon: `1:63`
- secondary horizons: `1:21`, `1:126`
- existing neutralization, expanding walk-forward, implementation costs, and promotion gates

The next execution sequence is: implement and test this provider layer -> prove cache-only coverage for all required historical symbols -> only then dispatch the unchanged amended HU-5 flagship.
