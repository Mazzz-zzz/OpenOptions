"""GET /iv-analysis/{underlying} — IV analysis: term structure, skew, smile, straddles."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contract, Snapshot

router = APIRouter()


def _days_to_expiry(expiry: date) -> int:
    return max(0, (expiry - date.today()).days)


def _find_by_delta(points, target_delta, option_type):
    """Find the contract closest to a target delta for a given option type."""
    best = None
    best_dist = float("inf")
    for snap, contract in points:
        if contract.option_type != option_type:
            continue
        if snap.delta_market is None:
            continue
        d = abs(float(snap.delta_market))
        dist = abs(d - target_delta)
        if dist < best_dist:
            best_dist = dist
            best = (snap, contract)
    return best


@router.get("/iv-analysis/{underlying}")
async def get_iv_analysis(
    underlying: str,
    lookback_days: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
):
    underlying = underlying.upper()

    # --- 1. Get latest snapshot per contract ---
    latest_snap_ids = (
        db.query(func.max(Snapshot.id))
        .join(Contract)
        .filter(Contract.underlying == underlying)
        .group_by(Snapshot.contract_id)
        .subquery()
    )

    current = (
        db.query(Snapshot, Contract)
        .join(Contract)
        .filter(Snapshot.id.in_(latest_snap_ids))
        .filter(Snapshot.market_iv.isnot(None))
        .filter(Snapshot.market_iv > 0)
        .all()
    )

    if not current:
        return {
            "term_structure": [], "skew_by_expiry": [], "smile": [],
            "iv_rank": None, "straddles": [], "spot": None,
            "historical_iv": [], "put_call_summary": None,
        }

    # Estimate spot from nearest ATM
    by_expiry = defaultdict(list)
    for snap, contract in current:
        by_expiry[contract.expiry].append((snap, contract))

    nearest_expiry = min(by_expiry.keys())
    spot = 0.0
    min_iv = float("inf")
    for snap, contract in by_expiry[nearest_expiry]:
        iv = float(snap.market_iv)
        if iv < min_iv:
            min_iv = iv
            spot = float(contract.strike)

    if spot <= 0:
        return {
            "term_structure": [], "skew_by_expiry": [], "smile": [],
            "iv_rank": None, "straddles": [], "spot": None,
            "historical_iv": [], "put_call_summary": None,
        }

    # --- 2. Term structure + skew + straddles per expiry ---
    term_structure = []
    straddles = []
    skew_by_expiry = []

    # Collect all smile points across all expiries
    all_smile_points = []

    for expiry in sorted(by_expiry.keys()):
        dte = _days_to_expiry(expiry)
        if dte <= 0:
            continue

        points = by_expiry[expiry]

        # Find nearest-ATM call and put
        best_call = None
        best_put = None
        best_call_dist = float("inf")
        best_put_dist = float("inf")

        for snap, contract in points:
            strike = float(contract.strike)
            dist = abs(strike - spot)
            if contract.option_type == "C" and dist < best_call_dist:
                best_call_dist = dist
                best_call = (snap, contract)
            elif contract.option_type == "P" and dist < best_put_dist:
                best_put_dist = dist
                best_put = (snap, contract)

        # ATM IV
        atm_ivs = []
        if best_call:
            atm_ivs.append(float(best_call[0].market_iv))
        if best_put:
            atm_ivs.append(float(best_put[0].market_iv))
        if not atm_ivs:
            continue
        atm_iv = sum(atm_ivs) / len(atm_ivs)

        # Model IV at ATM
        model_ivs = []
        if best_call and best_call[0].model_iv is not None:
            model_ivs.append(float(best_call[0].model_iv))
        if best_put and best_put[0].model_iv is not None:
            model_ivs.append(float(best_put[0].model_iv))
        atm_model_iv = sum(model_ivs) / len(model_ivs) if model_ivs else None

        atm_strike = float(best_call[1].strike if best_call else best_put[1].strike)

        term_structure.append({
            "expiry": expiry.isoformat(),
            "dte": dte,
            "atm_iv": round(atm_iv, 6),
            "atm_model_iv": round(atm_model_iv, 6) if atm_model_iv else None,
            "atm_strike": atm_strike,
        })

        # --- Skew: 25-delta put IV vs 25-delta call IV ---
        put_25d = _find_by_delta(points, 0.25, "P")
        call_25d = _find_by_delta(points, 0.25, "C")
        put_10d = _find_by_delta(points, 0.10, "P")
        call_10d = _find_by_delta(points, 0.10, "C")

        put_25d_iv = float(put_25d[0].market_iv) if put_25d else None
        call_25d_iv = float(call_25d[0].market_iv) if call_25d else None
        put_10d_iv = float(put_10d[0].market_iv) if put_10d else None
        call_10d_iv = float(call_10d[0].market_iv) if call_10d else None

        # Risk reversal = 25d put IV - 25d call IV (positive = put skew)
        risk_reversal = None
        if put_25d_iv is not None and call_25d_iv is not None:
            risk_reversal = round(put_25d_iv - call_25d_iv, 6)

        # Butterfly = avg(wings) - ATM (positive = fat tails / smile)
        butterfly = None
        if put_25d_iv is not None and call_25d_iv is not None:
            butterfly = round((put_25d_iv + call_25d_iv) / 2 - atm_iv, 6)

        # Per-expiry mispricing stats
        deviations = []
        total_vega = 0.0
        contracts_with_edge = 0
        for snap, contract in points:
            if snap.deviation is not None:
                deviations.append(float(snap.deviation))
            if snap.vega is not None:
                total_vega += abs(float(snap.vega))
            if snap.net_edge is not None and float(snap.net_edge) > 0:
                contracts_with_edge += 1

        avg_deviation = round(sum(deviations) / len(deviations), 6) if deviations else None
        max_abs_deviation = round(max(abs(d) for d in deviations), 6) if deviations else None

        skew_by_expiry.append({
            "expiry": expiry.isoformat(),
            "dte": dte,
            "atm_iv": round(atm_iv, 6),
            "put_25d_iv": round(put_25d_iv, 6) if put_25d_iv else None,
            "call_25d_iv": round(call_25d_iv, 6) if call_25d_iv else None,
            "put_10d_iv": round(put_10d_iv, 6) if put_10d_iv else None,
            "call_10d_iv": round(call_10d_iv, 6) if call_10d_iv else None,
            "risk_reversal": risk_reversal,
            "butterfly": butterfly,
            "avg_deviation": avg_deviation,
            "max_deviation": max_abs_deviation,
            "contracts_with_edge": contracts_with_edge,
            "total_contracts": len(points),
            "total_vega": round(total_vega, 2),
        })

        # --- Smile points for this expiry ---
        for snap, contract in points:
            if snap.delta_market is None:
                continue
            delta = float(snap.delta_market)
            moneyness = float(contract.strike) / spot if spot > 0 else 0
            all_smile_points.append({
                "expiry": expiry.isoformat(),
                "dte": dte,
                "strike": float(contract.strike),
                "moneyness": round(moneyness, 4),
                "delta": round(delta, 4),
                "option_type": contract.option_type,
                "market_iv": round(float(snap.market_iv), 6),
                "model_iv": round(float(snap.model_iv), 6) if snap.model_iv is not None else None,
                "deviation": round(float(snap.deviation), 6) if snap.deviation is not None else None,
                "net_edge": round(float(snap.net_edge), 2) if snap.net_edge is not None else None,
                "vega": round(float(snap.vega), 4) if snap.vega is not None else None,
            })

        # --- ATM straddle ---
        call_mid = float(best_call[0].mid) if best_call and best_call[0].mid else None
        put_mid = float(best_put[0].mid) if best_put and best_put[0].mid else None

        if call_mid is not None and put_mid is not None:
            straddle_price = call_mid + put_mid
            straddle_pct = (straddle_price / spot) * 100

            call_spread = (
                float(best_call[0].ask) - float(best_call[0].bid)
                if best_call[0].ask and best_call[0].bid else 0
            )
            put_spread = (
                float(best_put[0].ask) - float(best_put[0].bid)
                if best_put[0].ask and best_put[0].bid else 0
            )

            call_theta = float(best_call[0].theta) if best_call[0].theta is not None else None
            put_theta = float(best_put[0].theta) if best_put[0].theta is not None else None
            total_theta = round(call_theta + put_theta, 4) if call_theta is not None and put_theta is not None else None

            call_vega = float(best_call[0].vega) if best_call[0].vega is not None else None
            put_vega = float(best_put[0].vega) if best_put[0].vega is not None else None
            total_vega_straddle = round(call_vega + put_vega, 4) if call_vega is not None and put_vega is not None else None

            call_gamma = float(best_call[0].gamma) if best_call[0].gamma is not None else None
            put_gamma = float(best_put[0].gamma) if best_put[0].gamma is not None else None
            total_gamma = round(call_gamma + put_gamma, 8) if call_gamma is not None and put_gamma is not None else None

            # Theta/vega ratio: how much theta you earn per $ of vega risk
            theta_vega_ratio = None
            if total_theta is not None and total_vega_straddle and total_vega_straddle != 0:
                theta_vega_ratio = round(abs(total_theta) / total_vega_straddle, 4)

            # Vol premium: market ATM IV vs model ATM IV
            vol_premium = round(atm_iv - atm_model_iv, 6) if atm_model_iv is not None else None

            straddles.append({
                "expiry": expiry.isoformat(),
                "dte": dte,
                "atm_strike": atm_strike,
                "atm_iv": round(atm_iv, 6),
                "atm_model_iv": round(atm_model_iv, 6) if atm_model_iv else None,
                "vol_premium": vol_premium,
                "call_mid": round(call_mid, 4),
                "put_mid": round(put_mid, 4),
                "straddle_price": round(straddle_price, 4),
                "straddle_pct": round(straddle_pct, 2),
                "breakeven_up": round(spot + straddle_price, 2),
                "breakeven_down": round(spot - straddle_price, 2),
                "total_spread": round(call_spread + put_spread, 4),
                "total_theta": total_theta,
                "total_vega": total_vega_straddle,
                "total_gamma": total_gamma,
                "theta_vega_ratio": theta_vega_ratio,
                "risk_reversal": risk_reversal,
            })

    # --- 3. Put/Call summary across all contracts ---
    all_puts = [(s, c) for s, c in current if c.option_type == "P" and _days_to_expiry(c.expiry) > 0]
    all_calls = [(s, c) for s, c in current if c.option_type == "C" and _days_to_expiry(c.expiry) > 0]
    avg_put_iv = sum(float(s.market_iv) for s, c in all_puts) / len(all_puts) if all_puts else None
    avg_call_iv = sum(float(s.market_iv) for s, c in all_calls) / len(all_calls) if all_calls else None
    total_put_vega = sum(abs(float(s.vega)) for s, c in all_puts if s.vega is not None)
    total_call_vega = sum(abs(float(s.vega)) for s, c in all_calls if s.vega is not None)

    put_call_summary = {
        "avg_put_iv": round(avg_put_iv, 6) if avg_put_iv else None,
        "avg_call_iv": round(avg_call_iv, 6) if avg_call_iv else None,
        "put_call_iv_spread": round(avg_put_iv - avg_call_iv, 6) if avg_put_iv and avg_call_iv else None,
        "total_put_vega": round(total_put_vega, 2),
        "total_call_vega": round(total_call_vega, 2),
        "put_count": len(all_puts),
        "call_count": len(all_calls),
    }

    # --- 4. IV Rank from historical data ---
    cutoff = date.today() - timedelta(days=lookback_days)
    atm_lower = spot * 0.95
    atm_upper = spot * 1.05

    hour_bucket = func.date_trunc("hour", Snapshot.ts).label("bucket")
    historical_snaps = (
        db.query(hour_bucket, func.avg(Snapshot.market_iv).label("avg_iv"))
        .join(Contract)
        .filter(Contract.underlying == underlying)
        .filter(Contract.strike >= atm_lower)
        .filter(Contract.strike <= atm_upper)
        .filter(Snapshot.market_iv.isnot(None))
        .filter(Snapshot.market_iv > 0)
        .filter(Snapshot.ts >= cutoff)
        .group_by(hour_bucket)
        .order_by(hour_bucket)
        .all()
    )

    historical_iv = [
        {"ts": row.bucket.isoformat() if row.bucket else "", "iv": round(float(row.avg_iv), 6)}
        for row in historical_snaps
        if row.avg_iv is not None
    ]

    current_atm_iv = term_structure[0]["atm_iv"] if term_structure else None
    iv_rank = None
    iv_percentile = None
    iv_high = None
    iv_low = None

    if historical_iv and current_atm_iv is not None:
        hist_values = [h["iv"] for h in historical_iv]
        iv_high = round(max(hist_values), 6)
        iv_low = round(min(hist_values), 6)
        if iv_high > iv_low:
            iv_rank = round((current_atm_iv - iv_low) / (iv_high - iv_low) * 100, 1)
        below = sum(1 for v in hist_values if v < current_atm_iv)
        iv_percentile = round(below / len(hist_values) * 100, 1)

    # --- 5. Term structure slope ---
    ts_slope = None
    if len(term_structure) >= 2:
        near_iv = term_structure[0]["atm_iv"]
        far_iv = term_structure[-1]["atm_iv"]
        ts_slope = round(far_iv - near_iv, 6)  # positive = contango, negative = backwardation

    return {
        "spot": round(spot, 2),
        "term_structure": term_structure,
        "ts_slope": ts_slope,
        "skew_by_expiry": skew_by_expiry,
        "smile": all_smile_points,
        "straddles": straddles,
        "put_call_summary": put_call_summary,
        "iv_rank": {
            "current_iv": current_atm_iv,
            "rank": iv_rank,
            "percentile": iv_percentile,
            "high": iv_high,
            "low": iv_low,
            "lookback_days": lookback_days,
            "data_points": len(historical_iv),
        } if current_atm_iv is not None else None,
        "historical_iv": historical_iv,
    }
