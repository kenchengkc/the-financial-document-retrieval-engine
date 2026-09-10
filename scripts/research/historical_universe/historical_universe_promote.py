"""Compatibility entry point for historical-universe promotion."""

from fdre.research.historical_universe import promotion as _promotion
from fdre.research.historical_universe.promotion import *  # noqa: F403

_identity_claims = _promotion._identity_claims
_load_current = _promotion._load_current
_membership_verified = _promotion._membership_verified


if __name__ == "__main__":
    raise SystemExit(_promotion.main())
