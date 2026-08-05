from __future__ import annotations
import re
from collections import defaultdict
from .config import default_config
from .models import CatalystAssessment, CatalystClass, Instrument, NewsItem

# This rule engine is intentionally transparent. In production, replace or
# augment it with a point-in-time trained classifier plus entity/event models.
STRUCTURAL_TERMS = {
    "bankruptcy", "insolvency", "fraud", "delisting", "default",
    "accounting irregularities", "liquidity crisis", "going concern",
    "license revoked", "nationalisation", "nationalization",
}
FUNDAMENTAL_TERMS = {
    "guidance cut", "profit warning", "earnings miss", "revenue miss",
    "dividend suspended", "downgrade", "recall", "investigation",
    "secondary offering", "dilution", "capital raise",
}
MACRO_TERMS = {
    "rate decision", "central bank", "inflation", "cpi", "payrolls",
    "nonfarm", "employment", "gdp", "tariff", "sanctions",
}
EMOTIONAL_TERMS = {
    "panic", "risk-off", "technical selloff", "forced liquidation",
    "margin call", "stop-loss", "broad selloff", "profit taking",
}


def _contains(text: str, terms: set[str]) -> list[str]:
    lower = re.sub(r"\s+", " ", text.lower())
    return sorted(term for term in terms if term in lower)


def assess_catalyst(
    instrument: Instrument,
    items: list[NewsItem],
    minimum_source_count: int | None = None,
) -> CatalystAssessment:
    if minimum_source_count is None:
        minimum_source_count = default_config().catalyst.minimum_source_count

    if not items:
        probs = {c: 0.0 for c in CatalystClass}
        probs[CatalystClass.UNKNOWN] = 1.0
        return CatalystAssessment(
            label=CatalystClass.UNKNOWN,
            probabilities=probs,
            confidence=0.25,
            evidence=["No point-in-time catalyst data available"],
            hard_veto=True,
            veto_reason="CATALYST_DATA_MISSING",
        )

    hits = defaultdict(list)
    sources = set()
    weighted_relevance = 0.0

    for item in items:
        text = f"{item.headline} {item.body}"
        sources.add(item.source)
        weighted_relevance += max(0.0, min(1.0, item.relevance))
        for term in _contains(text, STRUCTURAL_TERMS):
            hits[CatalystClass.STRUCTURAL_REGIME_CHANGE].append(
                f"{item.source}: {term}"
            )
        for term in _contains(text, FUNDAMENTAL_TERMS):
            hits[CatalystClass.FUNDAMENTAL_REPRICING].append(
                f"{item.source}: {term}"
            )
        for term in _contains(text, MACRO_TERMS):
            hits[CatalystClass.SCHEDULED_MACRO].append(
                f"{item.source}: {term}"
            )
        for term in _contains(text, EMOTIONAL_TERMS):
            hits[CatalystClass.EMOTIONAL_TECHNICAL].append(
                f"{item.source}: {term}"
            )

    raw = {
        CatalystClass.STRUCTURAL_REGIME_CHANGE: 2.5 * len(hits[CatalystClass.STRUCTURAL_REGIME_CHANGE]),
        CatalystClass.FUNDAMENTAL_REPRICING: 1.8 * len(hits[CatalystClass.FUNDAMENTAL_REPRICING]),
        CatalystClass.SCHEDULED_MACRO: 1.2 * len(hits[CatalystClass.SCHEDULED_MACRO]),
        CatalystClass.EMOTIONAL_TECHNICAL: 1.0 * len(hits[CatalystClass.EMOTIONAL_TECHNICAL]),
        CatalystClass.LIQUIDITY_STRESS: 0.0,
        CatalystClass.UNKNOWN: 0.6 if not hits else 0.1,
    }
    total = sum(raw.values()) or 1.0
    probs = {k: v / total for k, v in raw.items()}
    label = max(probs, key=probs.get)
    evidence = hits.get(label, [])[:8]

    source_conf = min(1.0, len(sources) / max(1, minimum_source_count))
    relevance_conf = min(1.0, weighted_relevance / max(1, len(items)))
    confidence = 0.35 + 0.35 * source_conf + 0.30 * relevance_conf

    hard_veto = label in {
        CatalystClass.STRUCTURAL_REGIME_CHANGE,
        CatalystClass.FUNDAMENTAL_REPRICING,
    }
    veto_reason = None
    if hard_veto:
        veto_reason = f"CATALYST_{label.value.upper()}"
    elif len(sources) < minimum_source_count:
        hard_veto = True
        veto_reason = "INSUFFICIENT_INDEPENDENT_SOURCES"

    return CatalystAssessment(
        label=label,
        probabilities=probs,
        confidence=float(min(1.0, confidence)),
        evidence=evidence or ["No decisive keyword-level event found"],
        hard_veto=hard_veto,
        veto_reason=veto_reason,
    )
