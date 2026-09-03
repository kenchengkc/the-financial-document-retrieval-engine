# SGPPRB Historical Universe adjudication

This note freezes the read-only production replay used to adjudicate the known S&P 500 Historical
Universe blocker at membership row 580. It records evidence and conclusions only; it is not an
apply manifest and does not authorize mutation of a different live row state.

## Immutable SEC security-type evidence

Source:
`https://www.sec.gov/Archives/edgar/data/310158/000095012307011295/y37189bte424b2.htm`

The archived Schering-Plough prospectus explicitly defines the offered instrument as 6.00%
mandatory convertible preferred stock, identifies the defined 2007 Preferred Stock as listed under
`SGP PrB`, and separately identifies the issuer's common shares as listed under `SGP`.

- SEC evidence ID: `60bfff153f397f2de60824f48e72242973c0c93f453793c3d1838dedb2bc1a95`
- SEC payload SHA-256: `7d24d729d56338aeae547cbe9279e0246d810b218e75f7c14aab2a08ace4c6e4`

## Frozen production topology

Read-only replay plan ID:
`f386c335fcdbcfa3eb9633dad132f2454a03f4b05baa127802311c4d724ce580`

The known blocker is:

- membership row: `580`
- universe: `sp500`
- security ID: `798`
- effective interval: `[2009-12-31, 2010-01-22)`
- verification status: `provisional`
- confidence: `0.85`
- source: `lawcal/sp500-components-history`
- source hash: `a19b3fbb49fa327771a2c85af5c7c2e012d2a5c75130590a5b42c205b0ec666b`

Security `798` is currently modeled as `common_stock`, with no share class, and belongs to company
row `315`. The live company row carries CIK `0000310158`, current ticker `MRK`, and current name
`Merck & Co., Inc.`. The CIK exactly matches the historical SEC evidence.

There is exactly one overlapping `SGPPRB` identity on security `798`:

- identity row: `1082`
- effective interval: `[2009-12-31, 2010-01-23)`
- verification status: `verified`
- confidence: `0.98`
- source: `lawcal/sp500-components-history`
- source hash: `74607a310ab1dc269b5e9dc29972c55b7ecd5026d083a3bee4a2047df468f212`

## Decision

The planner produces exactly one rejection candidate: membership row `580`. Its unique overlapping
identity binds the membership to `SGPPRB`, and immutable SEC evidence establishes that `SGP PrB`
was preferred stock while `SGP` was the issuer's common-share ticker. Therefore the membership
cannot represent common-stock S&P 500 membership.

Identity row `1082` is intentionally **not** a rejection candidate in this plan because it is already
verified. The evidence exposes a separate security-master inconsistency: a verified identity for a
preferred instrument is attached to a security modeled as `common_stock`. That inconsistency should
be adjudicated separately rather than silently overriding a verified identity in the membership
cleanup.

## HU-5 impact

The replay staged only the supported membership rejection, recomputed HU-5 strict coverage, and
rolled the transaction back. Strict-eligible days remained `0 / 6088` before and after this single
rejection because other unresolved blockers still invalidate every day in the current window.

- before gate manifest: `6caeb287665a3a862662bc0e5cb8f18ee267e667f6a2090a6fb2022d84f24cf5`
- projected gate manifest: `13afb4c28cb71f628856407e840e1ccda0719572822c327987f4603d76fa79a4`

No production state was committed by the replay.
