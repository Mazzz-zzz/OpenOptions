"""GET /iv-analysis/{underlying} — IV term structure, rank, and ATM straddle data."""
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


@router.get("/iv-analysis/{underlying}")
async def get_iv_analysis(
    underlying: str,
    lookback_days: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
):
    """IV crush analysis: term structure, IV rank, ATM straddle pricing.

    Returns data for the IV Crush strategy page.
    """
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
            "term_structure": [],
            "iv_rank": None,
            "straddles": [],
            "spot": None,
            "historical_iv": [],
        }

    # Estimate spot from nearest ATM
    by_expiry: dict[date, list] = defaultdict(list)
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
            "term_structure": [],
            "iv_rank": None,
            "straddles": [],
            "spot": None,
            "historical_iv": [],
        }

    # --- 2. Term structure: ATM IV per expiry ---
    term_structure = []
    straddles = []

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

        # ATM IV = average of call and put IV at nearest strike
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

        term_structure.append({
            "expiry": expiry.isoformat(),
            "dte": dte,
            "atm_iv": round(atm_iv, 6),
            "atm_model_iv": round(atm_model_iv, 6) if atm_model_iv else None,
            "atm_strike": float(best_call[1].strike if best_call else best_put[1].strike),
        })

        # ATM straddle pricing
        call_mid = float(best_call[0].mid) if best_call and best_call[0].mid else None
        put_mid = float(best_put[0].mid) if best_put and best_put[0].mid else None

        if call_mid is not None and put_mid is not None:
            straddle_price = call_mid + put_mid
            straddle_pct = (straddle_price / spot) * 100
            # Breakeven = straddle price as % of spot (need to move this much to lose)
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
            total_theta = None
            if call_theta is not None and put_theta is not None:
                total_theta = round(call_theta + put_theta, 2)

            call_vega = float(best_call[0].vega) if best_call[0].vega is not None else None
            put_vega = float(best_put[0].vega) if best_put[0].vega is not None else None
            total_vega = None
            if call_vega is not None and put_vega is not None:
                total_vega = round(call_vega + put_vega, 2)

            straddles.append({
                "expiry": expiry.isoformat(),
                "dte": dte,
                "atm_strike": float(best_call[1].strike if best_call else best_put[1].strike),
                "call_mid": round(call_mid, 2),
                "put_mid": round(put_mid, 2),
                "straddle_price": round(straddle_price, 2),
                "straddle_pct": round(straddle_pct, 2),
                "breakeven_up": round(spot + straddle_price, 2),
                "breakeven_down": round(spot - straddle_price, 2),
                "total_spread": round(call_spread + put_spread, 2),
                "total_theta": total_theta,
                "total_vega": total_vega,
                "atm_iv": round(atm_iv, 6),
            })

    # --- 3. IV Rank: current ATM IV vs historical range ---
    # Get historical ATM IVs from snapshots over the lookback period
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

    # Compute IV rank
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
        # Percentile: % of observations below current
        below = sum(1 for v in hist_values if v < current_atm_iv)
        iv_percentile = round(below / len(hist_values) * 100, 1)

    return {
        "spot": round(spot, 2),
        "term_structure": term_structure,
        "straddles": straddles,
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
