"""GET /contracts — browse option contracts."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
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

    class Config:
        from_attributes = True


@router.get("/contracts")
async def list_contracts(
    underlying: Optional[str] = None,
    market: Optional[str] = None,
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
            )
            for c in contracts
        ],
        "total": total,
    }
