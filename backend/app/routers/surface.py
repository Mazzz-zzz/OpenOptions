"""GET /surface/{underlying} — vol surface data for 3D chart.
   GET /snapshots/{contract_id} — history for sparkline."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contract, Snapshot

router = APIRouter()


def _interpolate_row(values: list[float | None]) -> list[float | None]:
    """Linear interpolation to fill interior nulls in a row.

    Leaves leading/trailing nulls as-is (no extrapolation).
    """
    result = list(values)
    n = len(result)

    # Find all non-null indices
    known = [(i, v) for i, v in enumerate(result) if v is not None]
    if len(known) < 2:
        return result

    # Fill gaps between known points
    for k in range(len(known) - 1):
        i1, v1 = known[k]
        i2, v2 = known[k + 1]
        if i2 - i1 <= 1:
            continue
        for j in range(i1 + 1, i2):
            frac = (j - i1) / (i2 - i1)
            result[j] = v1 + frac * (v2 - v1)

    return result


def _estimate_spot(snapshots: list, contracts: list) -> float:
    """Estimate spot price as the strike with minimum IV on the nearest expiry."""
    if not snapshots:
        return 0

    # Group by expiry, find nearest
    by_expiry: dict = defaultdict(list)
    for snap, contract in zip(snapshots, contracts):
        by_expiry[contract.expiry].append((snap, contract))

    nearest_expiry = min(by_expiry.keys())
    nearest = by_expiry[nearest_expiry]

    # Find strike with minimum market_iv
    best_strike = None
    min_iv = float("inf")
    for snap, contract in nearest:
        iv = float(snap.market_iv) if snap.market_iv is not None else None
        if iv is not None and iv < min_iv:
            min_iv = iv
            best_strike = float(contract.strike)

    return best_strike or 0


@router.get("/surface/{underlying}")
async def get_surface(
    underlying: str,
    option_type: Optional[str] = Query(default=None, description="C or P, omit for both"),
    db: Session = Depends(get_db),
):
    """Return latest vol surface data points for Plotly 3D chart.

    Supports option_type filter, moneyness normalization,
    and linear interpolation of missing values.
    """
    underlying = underlying.upper()

    from sqlalchemy import func

    latest_snap_ids = (
        db.query(func.max(Snapshot.id))
        .join(Contract)
        .filter(Contract.underlying == underlying)
        .group_by(Snapshot.contract_id)
        .subquery()
    )

    query = (
        db.query(Snapshot, Contract)
        .join(Contract)
        .filter(Snapshot.id.in_(latest_snap_ids))
        .filter(Snapshot.market_iv.isnot(None))
        .filter(Snapshot.market_iv > 0)
    )

    if option_type and option_type.upper() in ("C", "P"):
        query = query.filter(Contract.option_type == option_type.upper())

    rows = query.all()

    if not rows:
        return {
            "x": [], "y": [], "x_moneyness": [],
            "z_market": [], "z_model": [],
            "points": [], "spot": None,
        }

    snaps = [r[0] for r in rows]
    contracts = [r[1] for r in rows]

    # Estimate spot for moneyness
    spot = _estimate_spot(snaps, contracts)

    # Group by expiry
    by_expiry: dict[str, list] = defaultdict(list)
    for snap, contract in rows:
        strike = float(contract.strike)
        moneyness = strike / spot if spot > 0 else 0

        # Filter to moneyness range 0.5 - 2.0 (removes extreme OTM noise)
        if spot > 0 and (moneyness < 0.5 or moneyness > 2.0):
            continue

        by_expiry[contract.expiry.isoformat()].append({
            "symbol": contract.symbol,
            "strike": strike,
            "moneyness": round(moneyness, 4) if spot > 0 else None,
            "expiry": contract.expiry.isoformat(),
            "option_type": contract.option_type,
            "bid": float(snap.bid) if snap.bid is not None else None,
            "ask": float(snap.ask) if snap.ask is not None else None,
            "mid": float(snap.mid) if snap.mid is not None else None,
            "market_iv": float(snap.market_iv) if snap.market_iv is not None else None,
            "model_iv": float(snap.model_iv) if snap.model_iv is not None else None,
            "delta_market": float(snap.delta_market) if snap.delta_market is not None else None,
            "delta_model": float(snap.delta_model) if snap.delta_model is not None else None,
            "vega": float(snap.vega) if snap.vega is not None else None,
            "gamma": float(snap.gamma) if snap.gamma is not None else None,
            "theta": float(snap.theta) if snap.theta is not None else None,
            "deviation": float(snap.deviation) if snap.deviation is not None else None,
            "net_edge": float(snap.net_edge) if snap.net_edge is not None else None,
        })

    if not by_expiry:
        return {
            "x": [], "y": [], "x_moneyness": [],
            "z_market": [], "z_model": [],
            "points": [], "spot": spot,
        }

    # Build arrays for Plotly surface
    expiries = sorted(by_expiry.keys())
    all_strikes = sorted({p["strike"] for points in by_expiry.values() for p in points})
    all_moneyness = [round(s / spot, 4) if spot > 0 else 0 for s in all_strikes]

    z_market = []
    z_model = []
    for expiry in expiries:
        points = {p["strike"]: p for p in by_expiry[expiry]}
        market_row: list[float | None] = []
        model_row: list[float | None] = []
        for strike in all_strikes:
            p = points.get(strike)
            market_row.append(p["market_iv"] if p and p["market_iv"] is not None else None)
            model_row.append(p["model_iv"] if p and p["model_iv"] is not None else None)
        # Interpolate to fill gaps
        z_market.append(_interpolate_row(market_row))
        z_model.append(_interpolate_row(model_row))

    # Flatten all points for detailed view
    all_points = [p for points in by_expiry.values() for p in points]

    return {
        "x": all_strikes,
        "x_moneyness": all_moneyness,
        "y": expiries,
        "z_market": z_market,
        "z_model": z_model,
        "points": all_points,
        "spot": spot,
    }


@router.get("/snapshots/{contract_id}")
async def get_snapshots(
    contract_id: int,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Return last N snapshots for a contract (for sparkline chart)."""
    snapshots = (
        db.query(Snapshot)
        .filter(Snapshot.contract_id == contract_id)
        .order_by(desc(Snapshot.ts))
        .limit(limit)
        .all()
    )

    return {
        "data": [
            {
                "id": s.id,
                "ts": s.ts.isoformat() if s.ts else None,
                "bid": float(s.bid) if s.bid is not None else None,
                "ask": float(s.ask) if s.ask is not None else None,
                "mid": float(s.mid) if s.mid is not None else None,
                "market_iv": float(s.market_iv) if s.market_iv is not None else None,
                "model_iv": float(s.model_iv) if s.model_iv is not None else None,
                "delta_market": float(s.delta_market) if s.delta_market is not None else None,
                "delta_model": float(s.delta_model) if s.delta_model is not None else None,
                "vega": float(s.vega) if s.vega is not None else None,
                "gamma": float(s.gamma) if s.gamma is not None else None,
                "theta": float(s.theta) if s.theta is not None else None,
                "deviation": float(s.deviation) if s.deviation is not None else None,
                "net_edge": float(s.net_edge) if s.net_edge is not None else None,
                "triggered_by": s.triggered_by,
            }
            for s in snapshots
        ]
    }
