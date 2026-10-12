"""Sources: boxes that make time series for plants, not necessarily power (constitution 2)."""

from kiozesim.errors import MissingInputError
from kiozesim.sources.base import Source
from kiozesim.sources.constant import ConstantParams, ConstantSource

__all__ = ["ConstantParams", "ConstantSource", "MissingInputError", "Source"]
