# HU-5 final membership adjudication

This branch resolves the final 15 provisional S&P 500 membership rows under a reviewed, fail-closed evidence manifest.

The planner requires the live provisional membership inventory to match the manifest exactly, including row ID, stable security, issuer CIK, interval bounds, prior source hash, and one exact overlapping identity anchor. Any required verified sibling membership is also pinned by row ID, security, CIK, interval, status, and source hash.

Supported actions are:

- `verify`: retain the existing interval and promote only when authoritative evidence supports it as-is.
- `correct_and_verify`: change only the reviewed interval boundary or boundaries, then verify. The planner refuses a no-op correction and the apply refuses any widening beyond the reviewed target.
- `reject`: leave the interval unchanged and mark the row rejected when authoritative evidence disproves the S&P 500 membership or proves it is a duplicate representation of an already-verified constituent.

Every authoritative claim is content-addressed from authority, immutable/source URL, and the exact assertion used for adjudication. The manifest ID binds all cases; each decision hash binds the live row contract, action, target interval, evidence IDs, sibling requirements, and reason; the plan ID binds all decisions and the manifest ID. The apply provenance hash additionally binds the plan ID and the prior source hash.

The temporary branch projection workflow is read-only and exists only to replay the reviewed manifest against production and freeze the exact plan ID. It must be removed before merge. Production mutation is not permitted from that workflow.
