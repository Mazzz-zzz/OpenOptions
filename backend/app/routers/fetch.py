"""POST /fetch/{underlying} — user-triggered data collection pipeline."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Alert, Contract, Dividend, Earning, Snapshot, Underlying
from app.services.detector import classify_mispricing
from app.services.deribit import DeribitClient
from app.services.pricing import (
    bs_delta,
    bs_gamma,
    bs_theta,
    bs_vega,
    compute_greeks,
    fit_svi_by_expiry,
    get_risk_free_rate,
    time_to_expiry,
)
from app.services.tastytrade import TastytradeClient

logger = logging.getLogger(__name__)

router = APIRouter()

CRYPTO_UNDERLYINGS = {"BTC", "ETH"}
COOLDOWN_MINUTES = 5


def _is_futures(symbol: str) -> bool:
    """Check if symbol is a futures product (e.g. /ES, /NQ, /ZW).

    Any symbol starting with / followed by 1-4 alpha chars is treated as futures.
    Tastytrade's API is the authority on whether the product code is valid.
    """
    if not symbol.startswith("/"):
        return False
    code = symbol[1:]
    return 1 <= len(code) <= 4 and code.isalpha()


@router.post("/fetch/{underlying:path}")
async def fetch_chain(
    underlying: str,
    force: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Trigger data collection for one underlying.

    Fetches full options chain, fits SVI surface per expiry,
    computes greeks + mispricing, writes snapshots + alerts.
    Supports equities (SPY), crypto (BTC), and futures (/ES).
    """
    underlying = underlying.upper()
    is_futures = _is_futures(underlying)

    if is_futures:
        # Futures: /ES -> product code ES
        product_code = underlying[1:]
    elif not underlying.isalpha() or len(underlying) > 10:
        raise HTTPException(status_code=400, detail=f"Invalid symbol '{underlying}'")

    # Cooldown check
    if not force:
        existing = db.query(Underlying).filter(Underlying.symbol == underlying).first()
        if existing and existing.last_fetched_at:
            fetched = existing.last_fetched_at
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES)
            if fetched > cutoff:
                mins_left = (fetched + timedelta(minutes=COOLDOWN_MINUTES) - datetime.now(timezone.utc)).seconds // 60 + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"{underlying} was fetched recently. Try again in ~{mins_left} min.",
                )

    is_crypto = underlying in CRYPTO_UNDERLYINGS
    if is_futures:
        source = "tastytrade"
        market = "futures"
    elif is_crypto:
        source = "deribit"
        market = "crypto"
    else:
        source = "tastytrade"
        market = "equity"

    # 1. Fetch chain from market data source
    if is_crypto:
        client = DeribitClient(settings.deribit_client_id, settings.deribit_client_secret)
    else:
        if not settings.tastytrade_refresh_token:
            raise HTTPException(status_code=503, detail="Tastytrade refresh token not configured")
        client = TastytradeClient(
            settings.tastytrade_client_id,
            settings.tastytrade_client_secret,
            settings.tastytrade_refresh_token,
        )

    market_metrics = None
    earnings_data = []
    dividends_data = []

    try:
        if is_futures:
            chain = await client.fetch_futures_chain(product_code)
        else:
            chain = await client.fetch_chain(underlying)

        # Fetch market metrics, earnings, dividends (equity only, non-fatal)
        if not is_crypto and not is_futures and isinstance(client, TastytradeClient):
            try:
                market_metrics = await client.fetch_market_metrics(underlying)
            except Exception as e:
                logger.warning(f"Market metrics failed for {underlying}: {e}")
            try:
                earnings_data = await client.fetch_earnings(underlying)
            except Exception as e:
                logger.warning(f"Earnings fetch failed for {underlying}: {e}")
            try:
                dividends_data = await client.fetch_dividends(underlying)
            except Exception as e:
                logger.warning(f"Dividends fetch failed for {underlying}: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch chain for {underlying}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch data from {source}: {str(e)}")
    finally:
        await client.close()

    if not chain:
        if is_futures:
            raise HTTPException(
                status_code=404,
                detail=f"No options available for {underlying}. The futures contract exists but has no listed options on Tastytrade.",
            )
        raise HTTPException(status_code=404, detail=f"No options data found for {underlying}")

    # 2. Get risk-free rate (non-fatal — fallback to 5% if FRED is down)
    try:
        r = await get_risk_free_rate(settings.fred_api_key)
    except Exception:
        logger.warning("FRED API failed, using fallback rate 0.05")
        r = 0.05

    # 3. Upsert contracts
    contract_map = _upsert_contracts(db, chain, market, source)

    # 4. Fit SVI surface per expiry
    underlying_price = chain[0].underlying_price
    surfaces = fit_svi_by_expiry(chain, underlying_price)

    # 5. Build map of existing undismissed alerts per contract
    contract_ids = [c.id for c in contract_map.values()]
    existing_alerts = (
        db.query(Alert)
        .join(Alert.snapshot)
        .filter(Snapshot.contract_id.in_(contract_ids), Alert.dismissed == False)
        .all()
    )
    # {contract_id: Alert} — latest undismissed alert per contract
    alert_by_contract = {}
    for a in existing_alerts:
        cid = a.snapshot.contract_id
        if cid not in alert_by_contract or a.id > alert_by_contract[cid].id:
            alert_by_contract[cid] = a

    # 6. Compute greeks + mispricing per contract
    snapshots = []
    alerts_raised = 0

    for quote in chain:
        contract = contract_map.get(quote.symbol)
        if not contract:
            continue

        T = time_to_expiry(quote.expiry)

        # Model IV from SVI fit
        fit = surfaces.get(quote.expiry)
        if fit is None:
            # SVI fit failed for this expiry — store snapshot without model data
            model_iv = None
            delta_model = None
        else:
            moneyness = math.log(quote.strike / underlying_price)
            model_iv = fit["predict"](moneyness)
            if model_iv and model_iv > 0:
                delta_model = bs_delta(underlying_price, quote.strike, T, r, model_iv, quote.option_type)
            else:
                delta_model = None

        # Market greeks
        if quote.market_iv and quote.market_iv > 0:
            delta_market = bs_delta(underlying_price, quote.strike, T, r, quote.market_iv, quote.option_type)
            vega = bs_vega(underlying_price, quote.strike, T, r, quote.market_iv)
            gamma = bs_gamma(underlying_price, quote.strike, T, r, quote.market_iv)
            theta = bs_theta(underlying_price, quote.strike, T, r, quote.market_iv, quote.option_type)
        else:
            delta_market = None
            vega = None
            gamma = None
            theta = None

        # Deviation (vol terms) and net edge (price terms via vega)
        deviation = None
        net_edge = None
        if model_iv is not None and quote.market_iv and quote.market_iv > 0:
            deviation = quote.market_iv - model_iv
            spread = quote.ask - quote.bid
            half_spread = spread / 2 if spread > 0 else 0
            if vega and vega > 0:
                price_edge = abs(deviation) * 100.0 * vega
                net_edge = price_edge - half_spread
            else:
                net_edge = None

        snap = Snapshot(
            contract_id=contract.id,
            bid=quote.bid,
            ask=quote.ask,
            mid=quote.mid,
            market_iv=quote.market_iv,
            model_iv=model_iv,
            delta_market=delta_market,
            delta_model=delta_model,
            vega=vega,
            gamma=gamma,
            theta=theta,
            deviation=deviation,
            net_edge=net_edge,
            triggered_by="user",
        )
        db.add(snap)
        snapshots.append(snap)

        # 7. Detect mispricing signals
        if (
            model_iv is not None
            and quote.market_iv
            and delta_market is not None
            and delta_model is not None
            and vega is not None
        ):
            signal = classify_mispricing(
                market_iv=quote.market_iv,
                model_iv=model_iv,
                delta_market=delta_market,
                delta_model=delta_model,
                bid=quote.bid,
                ask=quote.ask,
                vega=vega,
                vol_threshold=settings.vol_threshold / 100.0,  # convert vol points to decimal
            )
            if signal:
                prev = alert_by_contract.get(contract.id)
                if prev:
                    # Update existing alert to point at latest snapshot
                    prev.snapshot = snap
                    prev.signal_type = signal.signal_type
                    prev.confidence = signal.confidence
                else:
                    new_alert = Alert(
                        snapshot=snap,
                        signal_type=signal.signal_type,
                        confidence=signal.confidence,
                    )
                    db.add(new_alert)
                    alert_by_contract[contract.id] = new_alert
                alerts_raised += 1
            else:
                # Signal cleared — auto-dismiss stale alert
                prev = alert_by_contract.pop(contract.id, None)
                if prev:
                    prev.dismissed = True

    # 8. Upsert underlying tracking record + market metrics
    underlying_row = _upsert_underlying(
        db, underlying, market, source, underlying_price,
        len(snapshots), alerts_raised, market_metrics,
    )

    # 9. Upsert earnings and dividends
    if underlying_row and earnings_data:
        _upsert_earnings(db, underlying_row.id, earnings_data)
    if underlying_row and dividends_data:
        _upsert_dividends(db, underlying_row.id, dividends_data)

    db.commit()

    return {
        "underlying": underlying,
        "source": source,
        "snapshots": len(snapshots),
        "alerts_raised": alerts_raised,
        "expiries_fitted": sum(1 for v in surfaces.values() if v is not None),
        "expiries_failed": sum(1 for v in surfaces.values() if v is None),
    }


def _upsert_contracts(
    db: Session, chain: list, market: str, source: str
) -> dict:
    """Upsert contracts from chain data. Returns {symbol: Contract}."""
    symbols = [q.symbol for q in chain]
    existing = db.query(Contract).filter(Contract.symbol.in_(symbols)).all()
    existing_map = {c.symbol: c for c in existing}

    for quote in chain:
        if quote.symbol not in existing_map:
            contract = Contract(
                symbol=quote.symbol,
                underlying=quote.underlying,
                market=market,
                source=source,
                strike=quote.strike,
                expiry=quote.expiry,
                option_type=quote.option_type,
            )
            db.add(contract)
            existing_map[quote.symbol] = contract

    db.flush()  # get IDs assigned
    return existing_map


def _upsert_underlying(
    db: Session, symbol: str, market: str, source: str,
    spot: float, snapshot_count: int, alert_count: int,
    metrics: dict | None = None,
) -> Underlying:
    """Create or update the Underlying tracking record."""
    row = db.query(Underlying).filter(Underlying.symbol == symbol).first()
    now = datetime.now(timezone.utc)
    if row:
        row.last_fetched_at = now
        row.last_spot = spot
        row.last_snapshot_count = snapshot_count
        row.last_alert_count = alert_count
    else:
        row = Underlying(
            symbol=symbol,
            market=market,
            source=source,
            last_fetched_at=now,
            last_spot=spot,
            last_snapshot_count=snapshot_count,
            last_alert_count=alert_count,
        )
        db.add(row)

    if metrics:
        row.iv_index = metrics.get("iv_index")
        row.iv_index_5d_change = metrics.get("iv_index_5d_change")
        row.iv_rank = metrics.get("iv_rank")
        row.iv_percentile = metrics.get("iv_percentile")
        row.liquidity = metrics.get("liquidity")
        row.liquidity_rank = metrics.get("liquidity_rank")
        row.liquidity_rating = metrics.get("liquidity_rating")

    db.flush()
    return row


def _upsert_earnings(db: Session, underlying_id: int, earnings: list[dict]) -> None:
    """Insert earnings records, skipping duplicates."""
    existing = {
        e.occurred_date
        for e in db.query(Earning.occurred_date).filter(Earning.underlying_id == underlying_id).all()
    }
    for e in earnings:
        d = date.fromisoformat(e["occurred_date"]) if isinstance(e["occurred_date"], str) else e["occurred_date"]
        if d not in existing:
            db.add(Earning(underlying_id=underlying_id, occurred_date=d, eps=e.get("eps")))
            existing.add(d)


def _upsert_dividends(db: Session, underlying_id: int, dividends: list[dict]) -> None:
    """Insert dividend records, skipping duplicates."""
    existing = {
        d.occurred_date
        for d in db.query(Dividend.occurred_date).filter(Dividend.underlying_id == underlying_id).all()
    }
    for div in dividends:
        d = date.fromisoformat(div["occurred_date"]) if isinstance(div["occurred_date"], str) else div["occurred_date"]
        if d not in existing:
            db.add(Dividend(underlying_id=underlying_id, occurred_date=d, amount=div.get("amount")))
            existing.add(d)
