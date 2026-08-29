# HU-2 data PR acceptance note

This PR intentionally advances Historical Universe v1 without claiming final historical-universe coverage.

Acceptance for this slice:

- official SEC cumulative name/CIK data can be parsed offline and narrowed to membership-relevant names;
- exact issuer-name resolution is deterministic and fails closed on ambiguity;
- issuer resolution never fabricates historical ticker periods;
- multiple common-stock securities under one issuer remain ambiguous;
- a second independent historical membership source can be normalized offline with explicit attribution;
- identity-only ticker/name changes are not misclassified as index membership changes;
- two independent agreeing membership observations can verify an event through a uniquely resolved stable security;
- verified addition/removal pairs can materialize an evidence-bounded interval;
- the full batch emits a deterministic resolution/reconciliation/materialization audit;
- no new recurring infrastructure or bulk historical embeddings are introduced.

Still deferred after this PR:

- production download/workflow orchestration for source copies;
- comprehensive historical ticker/exchange identity-period backfill;
- persistence of derived issuer/security resolutions;
- present-day constituent-count reconciliation and final coverage thresholds;
- HU-2 completion claim and HU-3 public universe API.
