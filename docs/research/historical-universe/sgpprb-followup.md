# SGPPRB verified-identity follow-up

The membership-580 adjudication intentionally does not alter verified identity row 1082.

Production discovery shows identity row 1082 (`SGPPRB`, `[2009-12-31, 2010-01-23)`) is verified
while its parent security row 798 is typed `common_stock`. Immutable SEC evidence independently
establishes that `SGP PrB` was mandatory convertible preferred stock and that `SGP` was the issuer's
common-share ticker.

This is a separate security-master consistency problem, not permission to override a verified row
inside the membership cleanup. A future adjudication should first determine why row 1082 was marked
verified, whether security 798 represents the correct economic instrument, and whether correcting
the model requires rejecting/retyping the identity, splitting the security, or another explicit
lineage repair. Until that evidence is assembled, the fail-closed outcome is `unresolved`.
