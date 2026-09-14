# Exact SEC source-byte and parser replay

FDRE treats raw filing bytes as a separate reproducibility boundary from the persisted research panel. New SEC parses bind the persisted `DocumentElement` corpus to the exact byte string that was parsed and to an explicit parser version.

## Parse provenance

When `scripts.ingestion.download_filings` parses a filing, it now:

1. reads the retained filing once as bytes;
2. computes SHA-256 over that exact byte string;
3. rejects the parse if the bytes disagree with the document's expected SHA-256;
4. runs the versioned `HtmlFilingParser` on those same bytes;
5. computes a canonical SHA-256 over every ordered `ParsedElement` field;
6. stores the raw-byte hash, raw size, parser name/version, parsed-element hash, element count, and source URL under `Document.metadata_json.sec_parse_provenance`;
7. only then replaces the persisted `DocumentElement` rows.

Reading and parsing the same in-memory bytes prevents a hash-then-reopen race in which a local file could change between verification and parsing. Re-running the same parser version on the same bytes with a different element digest is treated as an invariant failure rather than silently replacing the corpus.

## Portable raw replay bundle

For documents whose original raw files are still retained, build a deterministic ZIP containing the exact source bytes plus their parse-provenance manifest:

```bash
python -m scripts.ingestion.sec_replay_bundle build \
  --accessions 0000320193-25-000079 0000320193-25-000057 \
  --output sec-source-replay.zip
```

Before writing the bundle, FDRE verifies that each retained file:

- matches `Document.sha256_hash` and the stored raw provenance hash;
- reproduces the stored parser output digest with the recorded parser version; and
- matches the currently persisted `DocumentElement` rows.

The archive uses fixed ZIP metadata, canonical manifest serialization, sorted accession order, and content-addressed raw members. Exporting the same verified inputs twice therefore produces the same bundle bytes and SHA-256 under the same runtime/compression implementation.

Verify and re-run every parser without a database or network request:

```bash
python -m scripts.ingestion.sec_replay_bundle verify \
  --bundle sec-source-replay.zip
```

Verification checks the manifest identity, exact archive-member set, each raw file's size and SHA-256, parser version compatibility, element count, and canonical parsed-element digest.

## Legacy boundary

This mechanism is intentionally fail-closed for historical documents that were parsed before exact source-byte provenance was recorded. A legacy document with no retained original bytes or no parse provenance is **not** upgraded by fetching the filing again: a later SEC response cannot prove it is byte-for-byte identical to the historical input.

Such documents remain reproducible from the persisted corpus through the research registry's panel-source layer, but they are not described as raw-byte/parser replayable. Raw-source replay becomes available only for parses where FDRE can bind and retain the exact original bytes.

The raw replay ZIP is a portable input artifact, not a Git-tracked dataset. `data/raw/` and generated bundles remain outside repository history; callers must retain a bundle anywhere they require durable source-level reproduction.
