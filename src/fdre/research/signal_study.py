"""Compatibility import for the signals package move."""

from fdre.research.signals import study as _study
from fdre.research.signals.study import *  # noqa: F403

_apply_benjamini_hochberg = _study._apply_benjamini_hochberg
_spearman = _study._spearman
_summarize_window = _study._summarize_window
