# HU-5 multi-class issuer outcome policy v1

Status: **PREDECLARED / FROZEN BEFORE AMENDED RERUN**

Policy version: `fdre-hu5-multiclass-outcome-v1`

This document defines the outcome mapping for issuer-level SEC filing events when a strict point-in-time historical-universe snapshot contains more than one simultaneously active listed security for the filing issuer. It is intentionally frozen before implementation-backed return evaluation under the amended contract.

The 2026-09-06 unchanged HU-5 rerun stopped before outcome scoring because the existing resolver required exactly one active security per filing CIK. That run remains immutable. No return result from the blocked multi-class events is used to choose this policy.

## Observation unit

The observation remains the **issuer filing accession**. One SEC filing produces at most one research observation for a given horizon.

A filing is never duplicated into one observation per share class. This prevents two correlated securities of the same issuer from being treated as independent signal observations, portfolio names, or statistical units.

## Eligible securities

For filing accession `A` with issuer CIK `C` and filing availability date `D`:

1. Resolve the strict historical-universe snapshot as of `D` using the existing HU-5 gate.
2. Select every verified active constituent security in that snapshot whose issuer CIK equals `C`.
3. Freeze that exact security set for the event. Future membership changes do not add another class to the event and do not remove a class that was selected at `D`.
4. Preserve the security IDs, historical symbols, membership source hashes, identity source hashes, and snapshot ID in event lineage.

Zero eligible securities remains fail-closed. A missing filing CIK or otherwise unresolved issuer lineage also remains fail-closed.

## Single-class outcome

If exactly one eligible security is active, retain the existing single-security outcome semantics. This policy does not select a different class or otherwise alter the single-class return definition.

## Multi-class outcome

If `N > 1` eligible securities are active, the issuer-level asset return for each predeclared event window is the equal-weight arithmetic mean of the component securities' total returns over the same start and end sessions:

`issuer_return = (1 / N) * sum(component_return_i)`

All component weights are therefore `1 / N`.

The benchmark-adjusted outcome is:

`abnormal_return = issuer_return - benchmark_return`

The benchmark return is subtracted exactly once. The share-class aggregation occurs before benchmark adjustment.

The existing HU-5 windows remain unchanged: `1:21`, `1:63`, and `1:126` sessions.

## Session alignment

For a multi-class event, the event and window endpoints use the benchmark trading-session calendar already supplied to the event study. Every selected component must have an adjusted-close observation at the required start and end session for that event/window.

If any selected component lacks a required endpoint, that event/window is unavailable. The implementation must **not** silently drop the missing class, renormalize the remaining weights, substitute another symbol, shorten the horizon, or carry a stale price forward.

## Explicit non-rules

The implementation must not choose a primary share class using:

- realized or forward returns;
- market performance observed after the filing;
- alphabetical/symbol ordering as an economic selection rule;
- current-day ticker preference;
- voting rights or class labels unless a separately sourced and predeclared rule is introduced later;
- market capitalization, float, volume, or liquidity unless a point-in-time dataset for that quantity is separately introduced and versioned before evaluation.

No such dataset is required for v1.

## Inference and implementation semantics

The filing remains one issuer observation after aggregation. Downstream walk-forward fold counts, IC calculations, portfolio cohort construction, turnover, concentration, and robustness slices must not count the component share classes as separate issuers.

The exact multi-class mapping and policy version must participate in the event-universe lineage digest and experiment definition so a change in component set or policy produces a new reproducibility identity.

## Failure behavior

The amended study remains fail-closed. It must return an explicit insufficient/unavailable state rather than guess when:

- filing CIK lineage cannot be resolved;
- no strict active security exists for the issuer on the event date;
- the strict universe date is invalid;
- a required multi-class component endpoint is unavailable; or
- component/security lineage is internally inconsistent.

## Amendment discipline

This is a methodology amendment to the unchanged HU-5 contract, not a reinterpretation of the 2026-09-06 run. Any subsequent change to weighting, security selection, session alignment, or missing-component handling requires a new policy version frozen before observing results under that change.
