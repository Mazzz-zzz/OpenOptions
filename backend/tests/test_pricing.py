"""Tests for Black-Scholes greeks and SVI surface fitting."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from app.services.pricing import (
    bs_delta,
    bs_implied_vol,
    bs_price,
    bs_vega,
    compute_greeks,
    fit_svi_by_expiry,
    fit_svi_slice,
    svi_total_variance,
    time_to_expiry,
)


class TestTimeToExpiry:
    def test_90_days(self):
        now = date(2026, 1, 1)
        expiry = date(2026, 4, 1)
        T = time_to_expiry(expiry, now)
        assert abs(T - 90 / 365.0) < 1e-10

    def test_floor_at_one_day(self):
        now = date(2026, 1, 1)
        expiry = date(2026, 1, 1)  # same day
        T = time_to_expiry(expiry, now)
        assert T == 1 / 365.0

    def test_past_expiry_floors(self):
        now = date(2026, 6, 1)
        expiry = date(2026, 1, 1)  # already expired
        T = time_to_expiry(expiry, now)
        assert T == 1 / 365.0

    def test_one_year(self):
        now = date(2026, 1, 1)
        expiry = date(2027, 1, 1)
        T = time_to_expiry(expiry, now)
        assert abs(T - 1.0) < 0.01


class TestBlackScholes:
    """Validate BS formulas against known values."""

    # ATM call: S=100, K=100, T=1, r=0.05, sigma=0.20
    S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.20

    def test_call_price_positive(self):
        price = bs_price(self.S, self.K, self.T, self.r, self.sigma, "C")
        assert price > 0
        # ATM call with these params should be ~10.45
        assert 9.0 < price < 12.0

    def test_put_price_positive(self):
        price = bs_price(self.S, self.K, self.T, self.r, self.sigma, "P")
        assert price > 0
        # ATM put should be less than call (positive r)
        call_price = bs_price(self.S, self.K, self.T, self.r, self.sigma, "C")
        assert price < call_price

    def test_put_call_parity(self):
        """C - P = S - K*exp(-rT)"""
        call = bs_price(self.S, self.K, self.T, self.r, self.sigma, "C")
        put = bs_price(self.S, self.K, self.T, self.r, self.sigma, "P")
        parity = self.S - self.K * math.exp(-self.r * self.T)
        assert abs((call - put) - parity) < 1e-10

    def test_call_delta_range(self):
        delta = bs_delta(self.S, self.K, self.T, self.r, self.sigma, "C")
        assert 0 < delta < 1
        # ATM call delta should be ~0.5
        assert 0.45 < delta < 0.65

    def test_put_delta_range(self):
        delta = bs_delta(self.S, self.K, self.T, self.r, self.sigma, "P")
        assert -1 < delta < 0
        # ATM put delta should be ~-0.5
        assert -0.55 < delta < -0.35

    def test_deep_itm_call_delta_near_one(self):
        delta = bs_delta(100, 50, 0.5, 0.05, 0.2, "C")
        assert delta > 0.99

    def test_deep_otm_call_delta_near_zero(self):
        delta = bs_delta(100, 200, 0.5, 0.05, 0.2, "C")
        assert delta < 0.01

    def test_vega_positive(self):
        vega = bs_vega(self.S, self.K, self.T, self.r, self.sigma)
        assert vega > 0

    def test_vega_atm_highest(self):
        """ATM vega should be higher than OTM vega."""
        vega_atm = bs_vega(100, 100, 1.0, 0.05, 0.2)
        vega_otm = bs_vega(100, 150, 1.0, 0.05, 0.2)
        assert vega_atm > vega_otm

    def test_compute_greeks_returns_dataclass(self):
        greeks = compute_greeks(self.S, self.K, self.T, self.r, self.sigma, "C")
        assert hasattr(greeks, "delta")
        assert hasattr(greeks, "vega")
        assert hasattr(greeks, "price")
        assert greeks.price > 0


class TestImpliedVol:
    def test_roundtrip_call(self):
        """Computing IV from a BS price should recover the original vol."""
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.25
        price = bs_price(S, K, T, r, sigma, "C")
        iv = bs_implied_vol(price, S, K, T, r, "C")
        assert iv is not None
        assert abs(iv - sigma) < 1e-6

    def test_roundtrip_put(self):
        S, K, T, r, sigma = 100, 90, 1.0, 0.05, 0.30
        price = bs_price(S, K, T, r, sigma, "P")
        iv = bs_implied_vol(price, S, K, T, r, "P")
        assert iv is not None
        assert abs(iv - sigma) < 1e-6

    def test_zero_price_returns_none(self):
        assert bs_implied_vol(0, 100, 100, 0.5, 0.05, "C") is None

    def test_negative_price_returns_none(self):
        assert bs_implied_vol(-1, 100, 100, 0.5, 0.05, "C") is None

    def test_below_intrinsic_returns_none(self):
        """Price below intrinsic value should return None."""
        # Deep ITM call: intrinsic ~= S - K*e^(-rT) ~= 50
        assert bs_implied_vol(0.01, 150, 100, 0.5, 0.05, "C") is None


class TestSVIFitting:
    def _generate_smile(self, n=20, T=0.25):
        """Generate a synthetic vol smile for testing."""
        moneyness = np.linspace(-0.3, 0.3, n)
        # Simple parabolic smile
        atm_vol = 0.25
        skew = -0.1
        convexity = 0.5
        ivs = atm_vol + skew * moneyness + convexity * moneyness**2
        return moneyness, ivs, T

    def test_svi_total_variance_shape(self):
        k = np.array([-0.2, -0.1, 0.0, 0.1, 0.2])
        w = svi_total_variance(k, a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1)
        assert w.shape == (5,)
        assert all(w > 0)

    def test_svi_total_variance_atm(self):
        """At k=m, total variance should be a + b*sigma."""
        w = svi_total_variance(np.array([0.0]), a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1)
        expected = 0.04 + 0.1 * 0.1  # a + b * sigma
        assert abs(w[0] - expected) < 1e-10

    def test_fit_svi_slice_success(self):
        moneyness, ivs, T = self._generate_smile()
        result = fit_svi_slice(moneyness, ivs, T)
        assert result is not None
        assert "params" in result
        assert "rmse" in result
        assert "predict" in result
        assert result["rmse"] < 0.05

    def test_fit_svi_slice_predict(self):
        moneyness, ivs, T = self._generate_smile()
        result = fit_svi_slice(moneyness, ivs, T)
        assert result is not None
        # Predict at ATM should be close to ATM vol
        predicted_iv = result["predict"](0.0)
        assert abs(predicted_iv - 0.25) < 0.05

    def test_fit_svi_slice_too_few_points(self):
        moneyness = np.array([0.0, 0.1, 0.2])
        ivs = np.array([0.25, 0.26, 0.28])
        result = fit_svi_slice(moneyness, ivs, 0.25)
        assert result is None

    def test_fit_svi_by_expiry(self):
        """Test fitting across multiple expiries."""
        from app.services.deribit import OptionQuote
        from datetime import timedelta

        underlying_price = 90000.0
        expiry1 = date.today() + timedelta(days=30)
        expiry2 = date.today() + timedelta(days=90)

        chain = []
        for expiry in [expiry1, expiry2]:
            for strike in range(70000, 120000, 5000):
                moneyness = math.log(strike / underlying_price)
                iv = 0.5 + 0.3 * moneyness**2 - 0.05 * moneyness
                chain.append(OptionQuote(
                    symbol=f"BTC-TEST-{strike}-C",
                    underlying="BTC",
                    strike=float(strike),
                    expiry=expiry,
                    option_type="C",
                    bid=100.0,
                    ask=110.0,
                    mid=105.0,
                    market_iv=iv,
                    underlying_price=underlying_price,
                    mark_price=105.0,
                ))

        surfaces = fit_svi_by_expiry(chain, underlying_price)
        assert len(surfaces) == 2
        assert expiry1 in surfaces
        assert expiry2 in surfaces
        # At least one should succeed
        assert any(v is not None for v in surfaces.values())
