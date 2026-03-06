"""Black-Scholes greeks and SVI volatility surface fitting."""
from __future__ import annotations

import math
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import date

import httpx
import numpy as np
from scipy.optimize import curve_fit, brentq

# Cache risk-free rate in-memory (refreshed on cold start)
_risk_free_rate: float | None = None


async def get_risk_free_rate(fred_api_key: str) -> float:
    """Fetch 1-month Treasury rate from FRED API. Cached in-memory."""
    global _risk_free_rate
    if _risk_free_rate is not None:
        return _risk_free_rate

    if not fred_api_key:
        _risk_free_rate = 0.05  # fallback
        return _risk_free_rate

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "DGS1MO",
                "api_key": fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
        )
        resp.raise_for_status()
        observations = resp.json()["observations"]
        for obs in observations:
            if obs["value"] != ".":
                _risk_free_rate = float(obs["value"]) / 100.0
                return _risk_free_rate

    _risk_free_rate = 0.05
    return _risk_free_rate


def time_to_expiry(expiry: date, now: date | None = None) -> float:
    """Years to expiry as a float."""
    if now is None:
        now = date.today()
    days = (expiry - now).days
    return max(days / 365.0, 1 / 365.0)  # floor at 1 day


# --- Black-Scholes ---


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes European option price."""
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    if option_type == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes delta."""
    d1 = _d1(S, K, T, r, sigma)
    if option_type == "C":
        return _norm_cdf(d1)
    else:
        return _norm_cdf(d1) - 1.0


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes vega (per 1% move in vol)."""
    d1 = _d1(S, K, T, r, sigma)
    return S * _norm_pdf(d1) * math.sqrt(T) / 100.0


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes gamma (rate of change of delta w.r.t. underlying price)."""
    d1 = _d1(S, K, T, r, sigma)
    return _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def bs_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes theta (time decay per calendar day, negative = losing value)."""
    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)
    term1 = -(S * _norm_pdf(d1) * sigma) / (2.0 * math.sqrt(T))
    if option_type == "C":
        annual = term1 - r * K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        annual = term1 + r * K * math.exp(-r * T) * _norm_cdf(-d2)
    return annual / 365.0  # per calendar day


def bs_implied_vol(
    price: float, S: float, K: float, T: float, r: float, option_type: str
) -> float | None:
    """Solve for implied volatility from option price using Brent's method."""
    if price <= 0:
        return None

    # Intrinsic value floor
    if option_type == "C":
        intrinsic = max(S - K * math.exp(-r * T), 0)
    else:
        intrinsic = max(K * math.exp(-r * T) - S, 0)
    if price < intrinsic - 1e-8:
        return None

    def objective(sigma):
        return bs_price(S, K, T, r, sigma, option_type) - price

    try:
        return brentq(objective, 0.001, 10.0, xtol=1e-8)
    except ValueError:
        return None


@dataclass
class Greeks:
    delta: float
    vega: float
    gamma: float
    theta: float
    price: float


def compute_greeks(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> Greeks:
    """Compute BS greeks for a single option."""
    return Greeks(
        delta=bs_delta(S, K, T, r, sigma, option_type),
        vega=bs_vega(S, K, T, r, sigma),
        gamma=bs_gamma(S, K, T, r, sigma),
        theta=bs_theta(S, K, T, r, sigma, option_type),
        price=bs_price(S, K, T, r, sigma, option_type),
    )


# --- SVI Surface Fitting ---


def svi_total_variance(k: np.ndarray, a: float, b: float, rho: float, m: float, sigma: float) -> np.ndarray:
    """SVI parametrization of total implied variance.

    w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

    where k = log(K/F) is log-moneyness.
    """
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma**2))


def fit_svi_slice(
    moneyness: np.ndarray, market_iv: np.ndarray, T: float
) -> dict | None:
    """Fit SVI to a single expiry slice.

    Args:
        moneyness: log(K/F) array
        market_iv: implied vol array (as decimal, e.g. 0.65)
        T: time to expiry in years

    Returns:
        dict with SVI params and predict function, or None on failure.
    """
    if len(moneyness) < 5:
        return None

    # Convert IV to total variance: w = sigma^2 * T
    total_var = (market_iv**2) * T

    # Initial guesses
    a0 = np.mean(total_var)
    b0 = 0.1
    rho0 = -0.3
    m0 = 0.0
    sig0 = 0.1

    # Parameter bounds to ensure no-arbitrage
    bounds = (
        [0, 0.001, -0.999, -2.0, 0.001],  # lower
        [np.max(total_var) * 3, 5.0, 0.999, 2.0, 5.0],  # upper
    )

    try:
        popt, _ = curve_fit(
            svi_total_variance,
            moneyness,
            total_var,
            p0=[a0, b0, rho0, m0, sig0],
            bounds=bounds,
            maxfev=5000,
        )

        # Check fit quality
        fitted = svi_total_variance(moneyness, *popt)
        residuals = total_var - fitted
        rmse = float(np.sqrt(np.mean(residuals**2)))

        if rmse > 0.05:
            return None

        a, b, rho, m, sigma = popt

        def predict(k: float) -> float:
            """Predict IV from log-moneyness."""
            w = svi_total_variance(np.array([k]), a, b, rho, m, sigma)[0]
            if w <= 0:
                return 0.0
            return float(np.sqrt(w / T))

        return {
            "params": {"a": a, "b": b, "rho": rho, "m": m, "sigma": sigma},
            "rmse": rmse,
            "predict": predict,
        }

    except (RuntimeError, ValueError):
        return None


def fit_svi_by_expiry(
    chain: list, underlying_price: float
) -> dict[date, dict]:
    """Group chain by expiry and fit SVI to each slice.

    Args:
        chain: list of OptionQuote objects with expiry, strike, market_iv
        underlying_price: current underlying price for moneyness calc

    Returns:
        dict mapping expiry date to SVI fit result (or None for failed fits)
    """
    from collections import defaultdict

    by_expiry: dict[date, list] = defaultdict(list)
    for quote in chain:
        if quote.market_iv > 0:
            by_expiry[quote.expiry].append(quote)

    surfaces = {}
    for expiry, quotes in by_expiry.items():
        T = time_to_expiry(expiry)
        moneyness = np.array([math.log(q.strike / underlying_price) for q in quotes])
        ivs = np.array([q.market_iv for q in quotes])

        # Sort by moneyness for stable fitting
        order = np.argsort(moneyness)
        moneyness = moneyness[order]
        ivs = ivs[order]

        fit = fit_svi_slice(moneyness, ivs, T)
        surfaces[expiry] = fit

    return surfaces
