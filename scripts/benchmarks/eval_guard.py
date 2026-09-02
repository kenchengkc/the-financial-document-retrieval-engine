"""Guard heavy read-eval scripts from silently billing Neon compute.

The retrieval/answer benchmarks read the full corpus, which wakes (and may
autoscale) the Neon compute. Require an explicit opt-in so a stray or automated
invocation can't run them against a Neon database unintentionally — point
DATABASE_URL at a branch, or set FDRE_ALLOW_PROD=1 to accept the cost.
"""

from __future__ import annotations

import os


def require_neon_optin() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if "neon.tech" in url and os.environ.get("FDRE_ALLOW_PROD") != "1":
        raise SystemExit(
            "Refusing to run a full-corpus benchmark against a Neon database — it "
            "wakes/scales prod compute and bills for it.\n"
            "  • Preferred: point DATABASE_URL at a Neon branch (isolated compute).\n"
            "  • Or set FDRE_ALLOW_PROD=1 to accept the cost and run anyway."
        )
