"""GET/DELETE /underlyings — tracked symbols management."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Underlying

router = APIRouter()

COOLDOWN_MINUTES = 5


@router.get("/underlyings")
def list_underlyings(
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    """List tracked underlyings with fetch status."""
    query = db.query(Underlying)
    if active_only:
        query = query.filter(Underlying.is_active == True)  # noqa: E712
    rows = query.order_by(Underlying.last_fetched_at.desc().nullslast()).all()

    now = datetime.now(timezone.utc)
    data = []
    for u in rows:
        on_cooldown = False
        if u.last_fetched_at:
            fetched = u.last_fetched_at
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            on_cooldown = now < fetched + timedelta(minutes=COOLDOWN_MINUTES)

        data.append({
            "symbol": u.symbol,
            "market": u.market,
            "source": u.source,
            "is_active": u.is_active,
            "last_fetched_at": u.last_fetched_at.isoformat() if u.last_fetched_at else None,
            "last_spot": float(u.last_spot) if u.last_spot else None,
            "last_snapshot_count": u.last_snapshot_count,
            "last_alert_count": u.last_alert_count,
            "on_cooldown": on_cooldown,
        })

    return {"data": data}


@router.delete("/underlyings/{symbol}")
def remove_underlying(
    symbol: str,
    db: Session = Depends(get_db),
):
    """Deactivate a tracked underlying (soft delete)."""
    symbol = symbol.upper()
    row = db.query(Underlying).filter(Underlying.symbol == symbol).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Underlying '{symbol}' not found")
    row.is_active = False
    db.commit()
    return {"symbol": symbol, "is_active": False}
