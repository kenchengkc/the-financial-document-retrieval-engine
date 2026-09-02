"""Financial Document Retrieval Engine package."""

from fdre.universe import (
    snapshot_to_dict,
    universe,
    universe_from_session,
    write_universe_snapshot,
)

__version__ = "0.1.0"

__all__ = [
    "snapshot_to_dict",
    "universe",
    "universe_from_session",
    "write_universe_snapshot",
]
