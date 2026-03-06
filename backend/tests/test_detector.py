"""Tests for mispricing signal detection."""
from __future__ import annotations

from app.services.detector import MispricingSignal, classify_mispricing, _assess_confidence


class TestClassifyMispricing:
    def test_no_signal_when_edge_negative(self):
        """Wide spread absorbs the vol edge — no signal."""
        # deviation = 0.01 (1 vol point), vega = 10, price_edge = 1*10 = $10
        # spread = 25, half_spread = 12.5, net_edge = 10 - 12.5 = -2.5 < 0
        result = classify_mispricing(
            market_iv=0.50,
            model_iv=0.49,
            delta_market=0.5,
            delta_model=0.49,
            bid=90.0,
            ask=115.0,  # spread=25, half_spread=12.5
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is None

    def test_surface_outlier_detected(self):
        """Large IV deviation with tight spread triggers surface_outlier.

        deviation = 0.10 (10 vol points), vega = 10
        price_edge = 10 * 10 = $100
        spread = 2, half_spread = 1
        net_edge = 100 - 1 = $99
        """
        result = classify_mispricing(
            market_iv=0.60,
            model_iv=0.50,
            delta_market=0.5,
            delta_model=0.45,
            bid=99.0,
            ask=101.0,
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is not None
        assert result.signal_type == "surface_outlier"
        assert abs(result.deviation - 0.10) < 1e-10
        assert abs(result.net_edge - 99.0) < 0.01

    def test_surface_outlier_negative_deviation(self):
        """Model IV > market IV should also trigger."""
        result = classify_mispricing(
            market_iv=0.40,
            model_iv=0.50,
            delta_market=0.5,
            delta_model=0.55,
            bid=99.0,
            ask=101.0,
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is not None
        assert result.signal_type == "surface_outlier"
        assert abs(result.deviation - (-0.10)) < 1e-10
        # net_edge same magnitude — uses abs(deviation)
        assert abs(result.net_edge - 99.0) < 0.01

    def test_greek_divergence_detected(self):
        """Small vol deviation but large delta divergence.

        deviation = 0.005 (below vol_threshold of 0.02), but delta diff = 0.12
        price_edge = 0.005 * 100 * 10 = $5
        half_spread = 0.5
        net_edge = $4.50 > 0 → signal
        """
        result = classify_mispricing(
            market_iv=0.500,
            model_iv=0.495,
            delta_market=0.50,
            delta_model=0.38,  # 12 delta points divergence
            bid=99.5,
            ask=100.5,
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is not None
        assert result.signal_type == "greek_divergence"
        assert abs(result.net_edge - 4.5) < 0.01

    def test_no_signal_below_threshold_no_delta_divergence(self):
        """Small deviation below threshold + no delta divergence → no signal."""
        # deviation = 0.001, price_edge = 0.001*100*10 = $1, half_spread = 0.5
        # net_edge = $0.50 > 0, BUT deviation < vol_threshold and delta_diff < 0.05
        result = classify_mispricing(
            market_iv=0.500,
            model_iv=0.499,
            delta_market=0.50,
            delta_model=0.499,
            bid=99.5,
            ask=100.5,
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is None

    def test_zero_spread_full_edge(self):
        """If bid == ask, half_spread is 0, full price_edge is net_edge."""
        result = classify_mispricing(
            market_iv=0.60,
            model_iv=0.50,
            delta_market=0.5,
            delta_model=0.45,
            bid=100.0,
            ask=100.0,
            vega=10.0,
            vol_threshold=0.02,
        )
        assert result is not None
        # price_edge = 0.10 * 100 * 10 = 100, half_spread = 0
        assert abs(result.net_edge - 100.0) < 0.01

    def test_zero_vega_no_signal(self):
        """If vega is zero, can't compute price edge → no signal."""
        result = classify_mispricing(
            market_iv=0.60,
            model_iv=0.50,
            delta_market=0.5,
            delta_model=0.45,
            bid=99.0,
            ask=101.0,
            vega=0.0,
            vol_threshold=0.02,
        )
        assert result is None

    def test_edge_barely_positive(self):
        """Edge just barely survives the spread."""
        # deviation = 0.03 (3 vol pts), vega = 5, price_edge = 3*5 = $15
        # spread = 28, half_spread = 14, net_edge = 15-14 = $1
        result = classify_mispricing(
            market_iv=0.53,
            model_iv=0.50,
            delta_market=0.50,
            delta_model=0.48,
            bid=86.0,
            ask=114.0,
            vega=5.0,
            vol_threshold=0.02,
        )
        assert result is not None
        assert result.signal_type == "surface_outlier"
        assert abs(result.net_edge - 1.0) < 0.01


class TestAssessConfidence:
    def test_high_confidence(self):
        """Large deviation ratio + edge is multiple of spread."""
        conf = _assess_confidence(
            deviation=0.10,     # 5x threshold
            net_edge=50.0,      # large dollar edge
            price_edge=55.0,
            half_spread=5.0,    # edge_ratio = 50/5 = 10
            vol_threshold=0.02,
        )
        assert conf == "high"

    def test_medium_confidence(self):
        conf = _assess_confidence(
            deviation=0.04,     # 2x threshold
            net_edge=3.0,
            price_edge=5.0,
            half_spread=2.0,    # edge_ratio = 3/2 = 1.5
            vol_threshold=0.02,
        )
        assert conf == "medium"

    def test_low_confidence(self):
        conf = _assess_confidence(
            deviation=0.021,    # barely above threshold
            net_edge=0.5,
            price_edge=1.0,
            half_spread=0.5,    # edge_ratio = 0.5/0.5 = 1.0
            vol_threshold=0.02,
        )
        assert conf == "low"

    def test_zero_spread_high_edge_ratio(self):
        """Zero spread → edge_ratio defaults to 10."""
        conf = _assess_confidence(
            deviation=0.10,
            net_edge=50.0,
            price_edge=50.0,
            half_spread=0.0,
            vol_threshold=0.02,
        )
        assert conf == "high"
