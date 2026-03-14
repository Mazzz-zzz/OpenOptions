"""Exogenous data endpoints — reads from the separate exogenous database."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_exo_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/exogenous/sources")
def list_sources(exo: Session = Depends(get_exo_db)):
    """List all registered exogenous data sources with row counts."""
    sources = exo.execute(text("SELECT id, key, name, source_type, enabled FROM exo_sources ORDER BY id")).fetchall()

    result = []
    for s in sources:
        # Get row count and date range for each source table
        table = f"exo_{s.key}"
        try:
            stats = exo.execute(text(f"SELECT COUNT(*) as cnt, MIN(captured_date) as min_date, MAX(captured_date) as max_date FROM {table}")).fetchone()
            count = stats.cnt
            min_date = str(stats.min_date) if stats.min_date else None
            max_date = str(stats.max_date) if stats.max_date else None
        except Exception:
            count = 0
            min_date = None
            max_date = None

        # Get distinct symbols for per_symbol sources
        symbols = 0
        if s.source_type == "per_symbol":
            try:
                symbols = exo.execute(text(f"SELECT COUNT(DISTINCT symbol) FROM {table}")).scalar() or 0
            except Exception:
                pass

        result.append({
            "id": s.id,
            "key": s.key,
            "name": s.name,
            "source_type": s.source_type,
            "enabled": s.enabled,
            "row_count": count,
            "symbols": symbols,
            "min_date": min_date,
            "max_date": max_date,
        })

    return {"data": result}


@router.get("/exogenous/tastytrade")
def list_tastytrade(
    date: Optional[str] = Query(default=None, description="Filter by date (YYYY-MM-DD), defaults to latest"),
    exo: Session = Depends(get_exo_db),
):
    """List Tastytrade exogenous data, defaulting to latest date per symbol."""
    if date:
        rows = exo.execute(
            text("""
                SELECT symbol, captured_date, spot_price, iv_rank, iv_percentile, iv_index, iv_5d_change, liquidity
                FROM exo_tastytrade
                WHERE captured_date = :dt
                ORDER BY symbol
            """),
            {"dt": date},
        ).fetchall()
    else:
        # Latest row per symbol
        rows = exo.execute(
            text("""
                SELECT DISTINCT ON (symbol) symbol, captured_date, spot_price, iv_rank, iv_percentile, iv_index, iv_5d_change, liquidity
                FROM exo_tastytrade
                ORDER BY symbol, captured_date DESC
            """)
        ).fetchall()

    return {
        "data": [
            {
                "symbol": r.symbol,
                "captured_date": str(r.captured_date),
                "spot_price": float(r.spot_price) if r.spot_price is not None else None,
                "iv_rank": float(r.iv_rank) if r.iv_rank is not None else None,
                "iv_percentile": float(r.iv_percentile) if r.iv_percentile is not None else None,
                "iv_index": float(r.iv_index) if r.iv_index is not None else None,
                "iv_5d_change": float(r.iv_5d_change) if r.iv_5d_change is not None else None,
                "liquidity": float(r.liquidity) if r.liquidity is not None else None,
            }
            for r in rows
        ]
    }
