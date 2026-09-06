# HU-5 market symbology cache preflight — 2026-09-06

This note freezes the no-return-evaluation production preflight that gates use of the versioned HU-5 market-provider symbology contract.

## Frozen execution

- Pull request: `#110` (`ops: validate frozen HU-5 market symbology cache`)
- Merge SHA: `03a84796df79f2866d3ea858fb8aa041ffccef74`
- Workflow: `HU-5 market symbology cache preflight`
- Run: `34046475377`
- Job: `101522304598`
- Result: **PASS**
- Restored market-cache source key: `fdre-market-Linux-34016265578`

## Frozen preflight state

- Schema: `fdre-hu5-market-symbology-preflight-v1`
- Preflight ID: `9218bc6b2de26a9f7bd993964c7ab3ffbe9f6a979b05b0dbcdd72bbc7bfeee86`
- Market symbology version: `fdre-hu5-market-symbology-v1`
- Market symbology manifest ID: `89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328`
- HU-5 issuer outcome policy: `fdre-hu5-multiclass-outcome-v1`
- Outcome mapping ID: `17c668c61da943beb48c9f3dd58325ab7222bb3836d21774eacfa07b0f704cd2`
- Strict eligible days: **6,088**
- Resolved filing events: **3,996**
- Multi-class events: **14**
- Historical component symbols: **270**
- Required historical market symbols including benchmark: **271**
- Provider symbols after frozen alias resolution: **264**
- Missing historical symbols: **0**
- Restricted `KFT -> MDLZ` event-window validation: **PASS**
- Market window requested: `2012-01-16` through `2027-04-19`
- Cache-only: **true**
- Return evaluation performed: **false**

The preflight therefore establishes that the existing frozen cache can address every historical symbol required by the unchanged HU-5 event set through the already-precommitted provider-alias layer, without changing historical event/security identity.

## Artifact provenance

- Artifact ID: `9993294887`
- Artifact name: `hu5-market-symbology-preflight-34046475377`
- Artifact size: **30,040 bytes**
- Artifact digest: `sha256:72fa5ed3c21bcc5e7c1778bf8996f67de582cb1b943c48627697aedc4e829207`
- Artifact files:
  - `preflight.json`
  - `market-cache-manifest.json`
- Market-cache manifest ID: `8fa0964c9fbf2c1adc2565fa878295a5d669b3612b95f7c700de90c9134b687e`
- Market-cache manifest entry count: **508**
- Artifact expires: `2026-12-05T16:45:41Z`

## Execution rule

The next canonical flagship execution may enable only `fdre-hu5-market-symbology-v1`, must preserve the existing HU-5 multi-class outcome policy and all sealed OOS methodology, and must fail before scoring if the same cache-only symbology preflight does not pass. The provider alias layer is operational symbology only; it must not rewrite historical PIT tickers in the HU-5 universe or event lineage.
