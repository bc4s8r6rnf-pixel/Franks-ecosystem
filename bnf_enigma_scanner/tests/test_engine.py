from datetime import datetime, timezone
from bnf_scanner.models import (
    AssetClass, CatalystAssessment, CatalystClass, DailyFeatures,
    Instrument, OrderFlowFeatures,
)
from bnf_scanner.engine import evaluate_long_setup


def test_structural_catalyst_vetoes():
    inst = Instrument("X", AssetClass.EQUITIES, "X", 0.01)
    daily = DailyFeatures(
        "X", datetime.now(timezone.utc), 70, 100, -30, -4, 5, -6,
        0.01, 100_000_000, 5,
    )
    catalyst = CatalystAssessment(
        CatalystClass.STRUCTURAL_REGIME_CHANGE,
        {CatalystClass.STRUCTURAL_REGIME_CHANGE: 0.9},
        0.95, ["bankruptcy"], True, "CATALYST_STRUCTURAL",
    )
    flow = OrderFlowFeatures(
        datetime.now(timezone.utc), 1000, 500, 0.5, -0.3,
        2.0, 0.001, 0.5, True, 72, 68, 71, True,
    )
    setup = evaluate_long_setup(inst, daily, catalyst, flow)
    assert setup.state.value == "rejected"
    assert "CATALYST_STRUCTURAL" in setup.vetoes
