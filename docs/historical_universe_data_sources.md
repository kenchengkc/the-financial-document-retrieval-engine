# HU-2 data source provenance

Historical Universe v1 uses source-specific adapters and retains source observations separately from derived resolution decisions.

## SEC cumulative CIK lookup

Source: `https://www.sec.gov/Archives/edgar/cik-lookup-data.txt`

Role: exact historical issuer-name to CIK evidence only. The SEC states that CIKs are unique and not recycled and that the lookup is historically cumulative for company names, including entities that no longer file. FDRE does not treat this file as historical ticker, exchange, security-class, or index-membership history.

## Wikipedia historical components

Source: `https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500`

Role: an independent historical S&P 500 membership-change observation source. The source page supplies effective dates, additions, removals, reasons, and references. FDRE records source attribution, does not bundle source content, and treats every parsed row as evidence requiring reconciliation.

Wikipedia text is currently licensed under CC BY-SA 4.0. Any redistributed Wikipedia-derived extracts should preserve attribution and comply with the applicable license terms.

Rows explicitly describing ticker/name changes are identity events and are skipped by the membership adapter rather than misclassified as index entries/exits.

## Trust boundary

Neither source is promoted to gold truth. Exact SEC issuer-name resolution can bridge unresolved membership evidence to a stable FDRE security only when a single common-stock security exists under that CIK. Multiple CIKs or multiple securities remain ambiguous. Verified membership still requires independent agreeing membership evidence and bounded interval construction.
