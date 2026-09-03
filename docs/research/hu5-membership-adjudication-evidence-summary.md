# HU-5 final membership evidence matrix

The checked-in manifest is the source of truth for exact row IDs, source hashes, identities, sibling contracts, URLs, and assertions. This note summarizes the reviewed disposition only.

- Verify as-is: ACT, ANRZQ, FERG, MHFI, RDDT, VMRK.
- Correct boundaries then verify: CTRA, NLOK, VIAC, WCG, WFM, WPX.
- Reject: MXB, SAIC, UA-C.

The distinction is semantic, not cosmetic. Ticker/name changes stay membership-continuous where the issuer/security remains in the index; event dates are corrected only where authoritative implementation/session evidence changes the half-open interval; false or duplicate constituent rows are rejected rather than promoted.

The membership checkpoint is complete only when a fresh production strict-membership audit reports zero provisional memberships and 6,088/6,088 eligible days. HU-5 itself remains incomplete until the residual identity periods are separately adjudicated and the identity-aware final gate also passes.
