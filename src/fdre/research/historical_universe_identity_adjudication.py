"""Compatibility import for the historical-universe package move."""

from fdre.research.historical_universe import identity_adjudication as _canonical
from fdre.research.historical_universe.identity_adjudication import *  # noqa: F403

_hash = _canonical._hash
_target_map = _canonical._target_map
_validate_case_shape = _canonical._validate_case_shape
_validate_final_identity_intervals = _canonical._validate_final_identity_intervals
_validate_topology_payload = _canonical._validate_topology_payload
