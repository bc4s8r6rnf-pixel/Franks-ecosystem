from __future__ import annotations
from collections import defaultdict
from .models import AssetClass, Setup, SetupState


def rank_setups(
    setups: list[Setup],
    max_per_asset_class: int = 3,
) -> list[Setup]:
    """Return only confirmed setups, ranked within asset class."""
    grouped: dict[AssetClass, list[Setup]] = defaultdict(list)
    for setup in setups:
        if setup.state == SetupState.CONFIRMED:
            grouped[setup.instrument.asset_class].append(setup)

    result: list[Setup] = []
    for _, group in grouped.items():
        group.sort(
            key=lambda s: (
                s.score,
                s.risk.rr_mean if s.risk else 0.0,
                abs(s.daily.divergence_pct),
            ),
            reverse=True,
        )
        result.extend(group[:max_per_asset_class])

    result.sort(key=lambda s: s.score, reverse=True)
    return result
