"""GET/POST /contracts — watchlist management."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contract

router = APIRouter()


class ContractResponse(BaseModel):
    id: int
    symbol: str
    underlying: str
    market: str
    source: str
    strike: float
    expiry: str
    option_type: str
    is_watchlisted: bool

    class Config:
        from_attributes = True


@router.get("/contracts")
async def list_contracts(
    underlying: Optional[str] = None,
    market: Optional[str] = None,
    watchlisted: Optional[bool] = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0, le=100000),
    db: Session = Depends(get_db),
):
    """List contracts with optional filters."""
    query = db.query(Contract)

    if underlying:
        query = query.filter(Contract.underlying == underlying.upper())
    if market:
        query = query.filter(Contract.market == market)
    if watchlisted is not None:
        query = query.filter(Contract.is_watchlisted == watchlisted)

    total = query.count()
    contracts = query.order_by(Contract.expiry, Contract.strike).offset(offset).limit(limit).all()

    return {
        "data": [
            ContractResponse(
                id=c.id,
                symbol=c.symbol,
                underlying=c.underlying,
                market=c.market,
                source=c.source,
                strike=float(c.strike),
                expiry=c.expiry.isoformat(),
                option_type=c.option_type,
                is_watchlisted=c.is_watchlisted,
            )
            for c in contracts
        ],
        "total": total,
    }


@router.post("/contracts/{contract_id}/watch")
async def watch_contract(contract_id: int, db: Session = Depends(get_db)):
    """Add contract to watchlist — enables EventBridge scheduled collection."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    contract.is_watchlisted = True
    db.commit()
    return {"id": contract_id, "is_watchlisted": True}


@router.delete("/contracts/{contract_id}/watch")
async def unwatch_contract(contract_id: int, db: Session = Depends(get_db)):
    """Remove contract from watchlist — disables scheduled collection."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    contract.is_watchlisted = False
    db.commit()
    return {"id": contract_id, "is_watchlisted": False}
