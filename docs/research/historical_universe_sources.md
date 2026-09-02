# Historical Universe source policy

Historical Universe v1 reconstructs point-in-time universe eligibility from multiple public evidence sources. No individual public source is treated as authoritative simply because it parses successfully. Source observations remain immutable; identity resolution, reconciliation, and interval materialization are derived steps that can be rerun as the security master improves.

## Source roles

### SEC cumulative CIK lookup

FDRE supports a local copy of:

`https://www.sec.gov/Archives/edgar/cik-lookup-data.txt`

The SEC describes CIKs as unique filer identifiers that are not recycled and describes this lookup as historically cumulative for company names, including entities that no longer file. HU-2 therefore uses it as **issuer-name -> CIK evidence**.

It is not used as:

- a historical ticker feed;
- an exchange-listing history;
- an S&P 500 membership source;
- evidence that a particular share class was the investable security on a historical date.

Resolution is intentionally conservative. FDRE normalizes punctuation and case, then requires an exact normalized company-name match. It does not strip legal suffixes, fuzzy-match names, or infer corporate successors. If the same normalized name maps to multiple CIKs, the result is ambiguous. If a resolved CIK maps to multiple common-stock securities in FDRE, the result remains ambiguous at the security layer.

The adapter is local-file only and can restrict the 13 MB lookup to names actually present in the membership batch.

### `shawnlinxl/snp-history`

HU-2 supports a local copy of the public CSV shape from:

`https://github.com/shawnlinxl/snp-history`

This source contributes normalized addition/removal observations, announcement and implementation dates, reported session timing, point-in-time tickers, names, and removal metadata. FDRE does not bundle or automatically download the upstream dataset. A successfully parsed row is still only one source observation and remains provisional until reconciliation justifies stronger status.

### Wikipedia historical S&P 500 components

HU-2 supports a local HTML copy of:

`https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500`

The page provides a long-running historical changes table with effective date, added
ticker/security, removed ticker/security, reason, and references. This overlaps the earlier
`snp-history` period and is useful for exact cross-source comparison. It is not treated as a
primary independent authority because public reconstructions can share upstream Wikipedia
evidence.

Wikipedia text is available under CC BY-SA 4.0. FDRE records Wikipedia attribution and the source page on every normalized observation and does not bundle a copy of the page. Anyone redistributing extracted Wikipedia-derived data should preserve attribution and comply with the applicable license terms.

Rows explicitly describing a ticker or company-name change are skipped by the membership adapter. Such rows are identity events, not index entry/exit events, and treating them as membership replacement would create false add/remove signals.

### `lawcal/sp500-components-history`

The production materialization source is pinned to an immutable commit. Its `created_at` field is
a required point-in-time validity condition, not optional metadata: a row is replayable only when
`date_added <= as_of < date_removed` and `as_of >= created_at`. This prevents a newly observed
ticker from being projected backward across the issuer's older membership history. When
`created_at > date_added`, the row can support membership evidence but cannot by itself establish
that the later symbol was valid at the reported membership start.

### SEC-filed IVV 2009 holdings

FDRE pins iShares S&P 500 Index Fund's N-Q accession `0001193125-10-044578` and parses its
2009-12-31 Schedule of Investments. The filing contains exactly 500 common-stock security names
and is used as the independent primary-source membership/count check for the target-window anchor.
It does not contain point-in-time tickers or issuer CIKs, so it cannot by itself create historical
identity periods. Exact filed names confirm 18 gaps in the lawcal snapshot; those memberships stay
blocked until dated identity evidence resolves the ticker and stable security.

## Evidence hierarchy

```text
raw local source copy
        |
        v
immutable normalized observation
        |
        +-------------------------------+
        |                               |
        v                               v
historical ticker/CIK identity      SEC historical-name evidence
        |                               |
        +---------------+---------------+
                        v
               stable security resolution
                        |
                        v
               cross-source reconciliation
                  /                 \
             verified             provisional
                        |
                        v
               bounded interval materialization
                        |
                        v
                 deterministic audit
```

Existing date-aware security identity periods always take priority over the SEC name fallback. SEC name evidence is used only when the normal historical identity resolver is unresolved. A unique SEC issuer match can bridge an event to a stable security only when exactly one common-stock security exists for that CIK. This does **not** create a historical ticker interval; strict HU snapshots still require valid identity-period evidence.

## Verification rules

- One membership source is provisional.
- Two or more distinct agreeing sources can verify an event.
- An exact lawcal interval boundary needs one exact external match; a lawcal date explicitly
  marked approximate needs two external exact matches to adjudicate the day.
- A boundary-corroborated interval remains identity-provisional when `created_at > date_added`.
- Opposite add/remove events for the same security and effective date remain provisional with a conflict code.
- Session-timing disagreement remains visible.
- Ambiguous CIKs, multiple share classes, or missing stable securities fail closed.
- Materialization requires evidence-bounded `addition -> removal` intervals.
- Orphan removals and trailing unbounded additions remain explicit audit issues.
- The current production constituent seed may be used as a present-day reconciliation check, never as evidence for an unknown historical start date.

## HU-2 audit contract

`run_hu2_reconstruction(...)` produces a deterministic batch audit containing:

- evidence and distinct-source counts;
- coverage start/end;
- issuer resolution counts (`resolved`, `ambiguous`, `unresolved`, `not_attempted`);
- stable-security resolution status and method counts;
- verified, provisional, and conflicting reconciled events;
- materialized verified/provisional intervals;
- materialization issue counts;
- a deterministic audit ID covering exact evidence, issuer resolutions, security resolutions, reconciliation identity, and materialization identity.

The audit is deliberately designed to make missing historical coverage measurable rather than filling gaps with guessed identities or dates.

## Operator examples

Normalize `snp-history` evidence and audit exact SEC historical-name matches:

```bash
python scripts/research/historical_universe/historical_universe_evidence.py history.csv \
  --adapter snp-history-csv \
  --observed-at 2026-08-29T20:00:00Z \
  --sec-cik-lookup cik-lookup-data.txt \
  --output normalized-snp-history.jsonl
```

Normalize the independent Wikipedia changes table:

```bash
python scripts/research/historical_universe/historical_universe_evidence.py historical-components.html \
  --adapter wikipedia-historical-components-html \
  --observed-at 2026-08-29T20:00:00Z \
  --sec-cik-lookup cik-lookup-data.txt \
  --output normalized-wikipedia-history.jsonl
```

Both commands are offline. Normalization and issuer resolution alone always report zero promoted memberships; verification requires stable-security resolution plus cross-source reconciliation.
