"""Mispricing signal detection and classification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MispricingSignal:
    signal_type: str  # 'surface_outlier' or 'greek_divergence'
    deviation: float  # market_iv - model_iv (vol decimal)
    net_edge: float  # price edge after spread ($)
    confidence: str  # 'high', 'medium', 'low'


def classify_mispricing(
    market_iv: float,
    model_iv: float,
    delta_market: float,
    delta_model: float,
    bid: float,
    ask: float,
    vega: float,
    vol_threshold: float = 0.02,
) -> MispricingSignal | None:
    """Classify a mispricing signal from snapshot data.

    Converts vol deviation to a dollar edge using vega, then subtracts
    the half-spread to get actionable net_edge in price terms.

    Two signal types:
    - surface_outlier: market IV deviates from SVI-fitted model IV
    - greek_divergence: delta computed from market IV vs model IV diverges significantly

    Returns None if no actionable signal.
    """
    deviation = market_iv - model_iv
    spread = ask - bid
    half_spread = spread / 2 if spread > 0 else 0

    # Convert vol deviation to price edge using vega.
    # Our vega is per 1 vol point (0.01 decimal), so multiply by deviation/0.01.
    if vega <= 0:
        return None
    price_edge = abs(deviation) * 100.0 * vega  # $ edge from vol mispricing
    net_edge = price_edge - half_spread

    # No signal if edge doesn't survive the spread
    if net_edge <= 0:
        return None

    # Check for surface outlier
    if abs(deviation) > vol_threshold:
        confidence = _assess_confidence(deviation, net_edge, price_edge, half_spread, vol_threshold)
        return MispricingSignal(
            signal_type="surface_outlier",
            deviation=deviation,
            net_edge=net_edge,
            confidence=confidence,
        )

    # Check for greek divergence (delta disagreement)
    delta_diff = abs(delta_market - delta_model)
    if delta_diff > 0.05:  # 5 delta points
        confidence = _assess_confidence(deviation, net_edge, price_edge, half_spread, vol_threshold)
        return MispricingSignal(
            signal_type="greek_divergence",
            deviation=deviation,
            net_edge=net_edge,
            confidence=confidence,
        )

    return None


def _assess_confidence(
    deviation: float, net_edge: float, price_edge: float, half_spread: float, vol_threshold: float
) -> str:
    """Assess confidence level of a signal.

    High: large deviation + edge is multiple of spread
    Medium: moderate deviation + edge survives spread
    Low: borderline
    """
    dev_ratio = abs(deviation) / vol_threshold if vol_threshold > 0 else 0
    edge_ratio = net_edge / half_spread if half_spread > 0 else 10.0

    if dev_ratio > 3.0 and edge_ratio > 2.0:
        return "high"
    elif dev_ratio > 1.5 and edge_ratio > 0.5:
        return "medium"
    else:
        return "low"
