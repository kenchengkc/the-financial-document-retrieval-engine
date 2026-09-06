# HU-5 amended flagship rerun — 2026-09-06

This note freezes the first canonical HU-5 execution after the versioned multi-class issuer-outcome policy and frozen market-provider symbology layer both passed their pre-outcome gates.

## Execution identity

- Canonical workflow: `flagship-risk-churn-acceleration.yml`
- Actions run: `34055143306`
- Job: `101545611259`
- Trigger: push to `main` from PR `#111`
- Code / merge SHA: `c0d455086cdf533eb27bedd8b9c07586bccf667b`
- Effective research inputs: `max_tickers=250`, `min_documents=6`, `max_uncached_market_fetches=300`
- Market mode: **cache-only**
- Market symbology profile: `fdre-hu5-market-symbology-v1`
- Restored market cache key: `fdre-market-Linux-34016265578`

The workflow had no Tiingo secret and no cache-save step. It therefore could not silently fetch or persist different market data during this execution.

## Pre-outcome gates

The in-job market symbology preflight completed **PASS** before the study was allowed to score:

- strict eligible days: **6,088 / 6,088**
- resolved filing events: **3,996**
- multi-class events: **14**
- historical component symbols: **270**
- required historical symbols including SPY: **271**
- provider symbols after frozen aliases: **264**
- missing historical symbols: **0**
- restricted `KFT -> MDLZ` window validation: **PASS**
- return evaluation performed by preflight: **false**
- universe gate manifest: `95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8`
- issuer-outcome policy: `fdre-hu5-multiclass-outcome-v1`
- outcome mapping: `17c668c61da943beb48c9f3dd58325ab7222bb3836d21774eacfa07b0f704cd2`
- market symbology manifest: `89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328`
- preflight ID: `9218bc6b2de26a9f7bd993964c7ab3ffbe9f6a979b05b0dbcdd72bbc7bfeee86`

This closes the historical-provider-symbol blocker. Historical event/security symbols remained unchanged in PIT lineage; provider aliases were only an addressing layer.

## Scientific result

The workflow completed successfully but emitted:

- `PRIMARY_RESULT=INSUFFICIENT`
- reason code: `multiclass_component_outcome_unavailable`
- experiment / insufficiency manifest ID: `3ddccc0ecbb4a51f7b938a030f2ec9526aef33dc6e5419ba5f057e24f8ece34a`
- primary observations: **0**
- OOS events: **0**
- eligible folds: **0**
- scored events: **0**

The exact reason is:

> At least one selected multi-class security lacks a required event-window endpoint; the frozen policy forbids dropping or renormalizing that class.

The artifact contains exactly three outcome-availability issues:

| Accession | Event date | Window | Reason | Missing component symbols |
| --- | --- | --- | --- | --- |
| `0001652044-26-000048` | 2026-04-30 | `1:126` | `benchmark_window_unavailable` | none |
| `0001652044-26-000071` | 2026-07-23 | `1:63` | `benchmark_window_unavailable` | none |
| `0001652044-26-000071` | 2026-07-23 | `1:126` | `benchmark_window_unavailable` | none |

The frozen SPY cache ends at **2026-09-04**. In `hu5_multiclass.py`, `benchmark_window_unavailable` is emitted when the event-session index plus the predeclared horizon extends beyond the available benchmark series, before component endpoint availability is tested. `missing_symbols` is empty for all three issues.

Therefore this is **right-censoring / not-yet-realized outcome data**, not a historical symbology failure and not evidence that GOOG or GOOGL is missing from the cache.

The affected SEC 10-Qs were accepted after the regular market close on 2026-04-29 and 2026-07-22, corresponding to event sessions 2026-04-30 and 2026-07-23 under the frozen event-study timing rule. Under the predeclared session horizons, the April event's 1:126 endpoint falls around 2026-10-29; the July event's 1:63 endpoint around 2026-10-21; and the final blocking July 1:126 endpoint around **2027-01-22**. The exact rerun gate is observability in the refreshed benchmark/component cache, not the calendar estimate itself.

## Artifact provenance

- Artifact ID: `9995782614`
- Artifact name: `flagship-risk-churn-acceleration-34055143306`
- Artifact size: **1,003,319 bytes**
- Artifact digest: `sha256:69a112a6c5e3584ac1b77f082624c148a49b900109f18e4469b61d27bed6e3b5`
- Artifact created: `2026-09-06T19:35:28Z`
- Artifact expires: `2026-12-05T19:31:13Z`
- Market-cache manifest ID: `8fa0964c9fbf2c1adc2565fa878295a5d669b3612b95f7c700de90c9134b687e`
- Market-cache manifest entries: **508**

Artifact files:

- `insufficiency-manifest.json`
- `market-cache-manifest.json`
- `market-symbology-preflight.json`
- `research-note.md`
- `summary.json`
- `universe-blockers.json`
- `universe-event-lineage.json`
- `universe-gate.json`
- `universe-remediation-queue.json`

## Interpretation and next gate

This run contains **no alpha evidence** either for or against the signal. It is neither `REJECT` nor `PROMOTE`.

No further methodology amendment is justified by this result. Do not drop the recent Alphabet events, shorten their horizons, substitute a different benchmark date, or renormalize around unavailable outcomes. Those actions would change the frozen experiment after observing its censoring state.

The next legitimate canonical rerun is after the final predeclared outcome horizon is observable. Operationally:

1. wait until the 2026-07-23 event's 1:126 benchmark endpoint has occurred (approximately 2027-01-22 under the expected exchange calendar);
2. refresh the market cache through that realized endpoint using the existing provider/symbology contract;
3. rerun the same cache/symbology preflight;
4. only if all frozen horizons are then available, run the unchanged canonical HU-5 study once.

Until then, the durable latest flagship state is **`INSUFFICIENT` due right-censored multi-class outcome horizons**.
