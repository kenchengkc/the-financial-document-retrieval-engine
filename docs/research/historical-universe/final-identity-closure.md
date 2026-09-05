# HU-5 final identity closure

**Status: production identity closure complete, 2026-09-05.** The reviewed 45-action plan
committed successfully. The merged HU-5 gate and independent identity-strict audit both confirm
6,088 of 6,088 calendar days from 2010-01-01 through 2026-09-01, inclusive.

This closes the historical-universe identity prerequisite for the flagship rerun. It does not
claim a new study result, additional realized outcomes, or a change to the precommitted methodology.

## Verified production result

| Measure | Frozen pre-state | Committed post-state |
| --- | ---: | ---: |
| Calendar days | 6,088 | 6,088 |
| Merged gate strict-eligible days | 1,426 | 6,088 |
| Merged gate invalid days | 4,662 | 0 |
| Independent identity-strict eligible days | 1,426 | 6,088 |
| Independent identity-strict blocked days | 4,662 | 0 |
| Relevant provisional identities | 39 | 0 |
| Provisional memberships | 0 | 0 |

The post-state was checked inside the apply transaction before commit, then read again in two
separate audit processes. The read-only closure audit uses a new PostgreSQL repeatable-read
transaction and compares both the full merged gate and the independent identity audit with the
committed apply report.

## Reviewed actions

Exactly 37 existing identities were verified without changing their boundaries. Five existing
identities were corrected and verified, and three identities were inserted. Every decision binds
security/CIK, source hash, prior and target intervals, symbol, sibling identities and memberships,
evidence IDs, and the frozen topology and SEC plan.

| Action | Identity / security | Applied interval change |
| --- | --- | --- |
| Correct SATS | identity 399 | Exclusive end 2026-06-24 |
| Correct CTRA | identity 1164 | Start 2021-10-04 |
| Correct WFM | identity 1170 | Start 2011-05-20 |
| Correct ANR | identity 1325 | Start 2011-06-02 |
| Correct WPX | identity 1401 | Exclusive end 2014-03-24 |
| Insert COG | identity 1507 / security 846 | [2021-10-03, 2021-10-04) |
| Insert ECHO | identity 1508 / security 399 | [2026-06-24, open) |
| Insert SPGI | identity 1509 / security 778 | [2016-04-28, 2016-05-03) |

The COG bridge preserves the Sunday before CTRA began trading. SATS and ECHO share the exact
2026-06-24 transition boundary. The 16 missing-symbol results from the bounded SEC crawl were
adjudicated using the reviewed continuity and authoritative evidence recorded in the manifest;
the genuine SATS/ECHO symbol conflict was resolved through the issuer's dated ticker transition.

The checked-in
[reviewed manifest](../../../src/fdre/research/historical_universe_identity_adjudication_manifest.py)
contains the evidence URLs and assertions. The
[planner](../../../src/fdre/research/historical_universe_identity_adjudication.py)
reconstructs and cryptographically validates the exact frozen inventory.

## Frozen provenance

| Stage | GitHub Actions run | Artifact ID | Archive SHA-256 |
| --- | --- | --- | --- |
| Residual SEC evidence | [33843412242](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33843412242) | 9925706591 | `aeefd076f5301c4fae186708a6b799caedfd9ce7e1dfe94bc54c7c7361605cf1` |
| Rolled-back projection | [33908491559](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33908491559) | 9950441480 | `26595955dc6799e72bac5a6aec8e9ec7ac5f7f2d1d000665da0405c533da05ee` |
| Production apply and independent audits | [33971576262](https://github.com/kenchengkc/the-financial-document-retrieval-engine/actions/runs/33971576262) | 9971101844 | `ac326c69c936a859a6af0155653d0c55e3ca4464b5cf130004f77223e0dbf0cc` |

- Frozen pre-state identity audit:
  `b5dc9108a2cfbbb9d4717aa1cb52dc751e31734bb5188ec5d8e05499db64245a`.
- Frozen topology:
  `5e30e1075c71c6578fd60e550ae1518538b680f35c9c9003d4b48372a74821e9`.
- Frozen residual SEC plan:
  `b9e7eebeb8af54f27f051c81a8497be572d31f8de1a79f9c8826c2a4664fe71d`.
- Reviewed adjudication manifest:
  `96628d4fc51ffd0c8322cffd092d8526d286fcf71a262171bb7ebcf042fa8a22`.
- Reviewed adjudication plan:
  `d73f752121f42f642f4881e295d7e7b72b56479e276265b7942df274484cc271`.
- Projected and committed merged gate:
  `95d53555924f4e60f929ad9377f188a70aba808f82697cf8c9b437aa047463b8`.
- Projected and committed merged-gate input provenance:
  `0662048623bc4a3dc0572ee56a3896de3d2ae6aea0ddaa34227bdd755e27c256`.
- Independent committed identity-strict audit:
  `3bbf94aae7e575043e782af2b8448ae4d0090bd396f43558fda0b84a7a1a5595`.
- Projection identity-strict audit:
  `88b730c031ae3cac1340874d726378e38c5fc9b3851b538703514ef30418c96b`.

The two identity-audit IDs differ because projection inserts used negative IDs to avoid advancing
PostgreSQL sequences, while production assigned IDs 1507–1509. The merged gate hashes semantic
row contents and is identical in projection and production.

Production ran reviewed commit `3e4f2df5a7d57c6d3cbd6da1ccb317f6cba9451a`, merged in
[PR #100](https://github.com/kenchengkc/the-financial-document-retrieval-engine/pull/100), after
[PR #98](https://github.com/kenchengkc/the-financial-document-retrieval-engine/pull/98) and
[PR #99](https://github.com/kenchengkc/the-financial-document-retrieval-engine/pull/99).
The exact owner command is retained in
[issue #84, comment 5552435885](https://github.com/kenchengkc/the-financial-document-retrieval-engine/issues/84#issuecomment-5552435885).

Artifact `hu5-final-identity-apply-33971576262` contains the frozen topology, SEC evidence,
projection, `run-provenance.json`, `apply.json`, `identity-strict-coverage.json`, and
`closure-audit.json`. Its configured 90-day retention expires 2026-12-04; the inputs and measured
IDs above remain documented in Git. Generated evidence artifacts are not committed to the repo.

## Transaction and operational controls

The owner-only one-shot workflow required the exact manifest, plan, and 37/5/3 action counts on
issue #84. It checked artifact metadata and archive bytes before opening the production
transaction. The writer required `--apply` and `FDRE_ALLOW_PROD=1`, held the input tables stable,
revalidated the frozen pre-state and siblings, staged all 45 actions, and required both closure
gates plus exact projected merged-gate provenance before commit. Live drift caused failure;
the manifest never adapted automatically.

The temporary projection workflow and its ops branch were removed after the successful
projection. The apply workflow was disabled after the independent production audits passed and
removed from the repository as part of closure cleanup. The reusable guarded writer and read-only
audits remain available for inspection; the original plan cannot replay against the changed
post-state.

Backend and frontend CI passed for the reviewed apply revision. Backend CI ran 514 tests,
including a PostgreSQL test proving that each input-table lock rejects concurrent writes until
rollback; Ruff, mypy, migrations, retrieval-index checks, Compose, and actionlint also passed.
Frontend audit, lint, types, build, and 20 Playwright tests passed.

## Read-only verification

Download artifact `9971101844` from run `33971576262`, verify its digest, and run:

```bash
python -m scripts.research.historical_universe.historical_universe_identity_strict_coverage \
  --database-url "$DATABASE_URL" \
  --universe-code sp500 --window-start 2010-01-01 --window-end 2026-09-01 \
  --output identity-strict-coverage.json

python -m scripts.research.historical_universe.historical_universe_identity_closure_audit \
  --database-url "$DATABASE_URL" \
  --apply-report /path/to/downloaded/apply.json \
  --output closure-audit.json
```

The second command rejects any change to the frozen committed gate or audit, even if the total
eligible-day count remains 6,088. A later intentional universe revision requires a new provenance
record.
