"""NQ projection-zone research engine.

Data-agnostic: point it at any OHLC series and every statistic in the brief is
computed the same way, which is what makes the null models directly comparable
to real results.
"""

from . import analysis, data, nullmodel, projections, swings  # noqa: F401

__all__ = ["analysis", "data", "nullmodel", "projections", "swings"]
