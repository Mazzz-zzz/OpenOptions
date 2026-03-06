"""GET /underlyings — list fetched symbols."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Underlying

router = APIRouter()


@router.get("/underlyings")
def list_underlyings(
    db: Session = Depends(get_db),
):
    """List all underlyings that have been fetched."""
    rows = db.query(Underlying).order_by(Underlying.last_fetched_at.desc().nullslast()).all()

    return {
        "data": [
            {
                "symbol": u.symbol,
                "market": u.market,
                "source": u.source,
                "last_fetched_at": u.last_fetched_at.isoformat() if u.last_fetched_at else None,
                "last_spot": float(u.last_spot) if u.last_spot else None,
                "last_snapshot_count": u.last_snapshot_count,
                "last_alert_count": u.last_alert_count,
            }
            for u in rows
        ]
    }
