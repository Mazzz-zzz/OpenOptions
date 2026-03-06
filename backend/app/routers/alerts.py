"""GET /alerts — paginated alert list. POST /alerts/{id}/dismiss."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Alert, Contract, Snapshot

router = APIRouter()


class AlertResponse(BaseModel):
    id: int
    signal_type: str
    confidence: Optional[str] = None
    dismissed: bool
    created_at: str
    # Snapshot fields
    snapshot_id: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    market_iv: Optional[float] = None
    model_iv: Optional[float] = None
    vega: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    deviation: Optional[float] = None
    net_edge: Optional[float] = None
    triggered_by: Optional[str] = None
    # Contract fields
    symbol: str
    underlying: str
    strike: float
    expiry: str
    option_type: str

    class Config:
        from_attributes = True


@router.get("/alerts")
async def get_alerts(
    cursor: Optional[int] = None,
    limit: int = Query(default=50, le=200),
    signal_type: Optional[str] = None,
    underlying: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Cursor-based paginated alert list, newest first."""
    query = (
        db.query(Alert)
        .join(Alert.snapshot)
        .join(Snapshot.contract)
        .filter(Alert.dismissed == False)
    )

    if signal_type:
        query = query.filter(Alert.signal_type == signal_type)

    if underlying:
        query = query.filter(Contract.underlying == underlying.upper())

    if cursor is not None:
        query = query.filter(Alert.id < cursor)

    query = query.order_by(Alert.id.desc()).limit(limit + 1)

    alerts = query.options(
        joinedload(Alert.snapshot).joinedload(Snapshot.contract)
    ).all()

    has_more = len(alerts) > limit
    alerts = alerts[:limit]

    data = []
    for alert in alerts:
        snap = alert.snapshot
        contract = snap.contract
        data.append(
            AlertResponse(
                id=alert.id,
                signal_type=alert.signal_type,
                confidence=alert.confidence,
                dismissed=alert.dismissed,
                created_at=alert.created_at.isoformat() if alert.created_at else "",
                snapshot_id=snap.id,
                bid=float(snap.bid) if snap.bid is not None else None,
                ask=float(snap.ask) if snap.ask is not None else None,
                mid=float(snap.mid) if snap.mid is not None else None,
                market_iv=float(snap.market_iv) if snap.market_iv is not None else None,
                model_iv=float(snap.model_iv) if snap.model_iv is not None else None,
                vega=float(snap.vega) if snap.vega is not None else None,
                gamma=float(snap.gamma) if snap.gamma is not None else None,
                theta=float(snap.theta) if snap.theta is not None else None,
                deviation=float(snap.deviation) if snap.deviation is not None else None,
                net_edge=float(snap.net_edge) if snap.net_edge is not None else None,
                triggered_by=snap.triggered_by,
                symbol=contract.symbol,
                underlying=contract.underlying,
                strike=float(contract.strike),
                expiry=contract.expiry.isoformat(),
                option_type=contract.option_type,
            )
        )

    return {
        "data": data,
        "next_cursor": alerts[-1].id if has_more and alerts else None,
    }


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: int, db: Session = Depends(get_db)):
    """Dismiss a specific alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.dismissed = True
    db.commit()
    return {"id": alert_id, "dismissed": True}
