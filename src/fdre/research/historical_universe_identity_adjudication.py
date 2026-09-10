"""Compatibility import for the historical-universe package move."""

from fdre.research.historical_universe.identity_adjudication import *  # noqa: F403
from fdre.research.historical_universe.identity_adjudication import (
    _hash as _hash,
    _target_map as _target_map,
    _validate_case_shape as _validate_case_shape,
    _validate_final_identity_intervals as _validate_final_identity_intervals,
    _validate_topology_payload as _validate_topology_payload,
)
