"""Tastytrade REST client for US equity options chain data."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

API_URL = "https://api.tastyworks.com"
API_VERSION = "20251101"
BATCH_SIZE = 100
MAX_CONCURRENT = 5

logger = logging.getLogger(__name__)


@dataclass
class OptionQuote:
    symbol: str
    underlying: str
    strike: float
    expiry: date
    option_type: str  # 'C' or 'P'
    bid: float
    ask: float
    mid: float
    market_iv: float  # implied vol as decimal
    underlying_price: float


class TastytradeClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._http = httpx.AsyncClient(
            base_url=API_URL,
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Accept-Version": API_VERSION,
            },
        )

    async def _ensure_token(self):
        """Authenticate using refresh token to get access token."""
        resp = await self._http.post(
            "/oauth/token",
            json={
                "grant_type": "refresh_token",
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._http.headers["Authorization"] = f"Bearer {data['access_token']}"
        if "refresh_token" in data:
            self.refresh_token = data["refresh_token"]

    async def fetch_chain(self, underlying: str) -> list[OptionQuote]:
        """Fetch full options chain for a US equity symbol."""
        await self._ensure_token()

        stock_price = await self._get_stock_price(underlying)

        all_options = await self._get_option_chain(underlying)

        # Filter out expired contracts only — keep everything else
        options = []
        for opt in all_options:
            exp_str = opt.get("expiration-date", "")
            if not exp_str:
                continue
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if exp <= date.today():
                continue
            options.append(opt)

        if not options:
            return []

        symbols = [opt["symbol"] for opt in options]
        market_data = await self._get_market_data_batched(symbols)

        quotes = []
        for opt in options:
            sym = opt["symbol"]
            md = market_data.get(sym)
            if md is None:
                continue

            bid = float(md.get("bid") or 0)
            ask = float(md.get("ask") or 0)
            if bid <= 0 and ask <= 0:
                continue

            mid_val = (bid + ask) / 2
            strike = float(opt["strike-price"])
            expiry = datetime.strptime(opt["expiration-date"], "%Y-%m-%d").date()
            option_type = opt.get("option-type", "C")

            # Tastytrade provides IV as decimal (e.g. 0.208)
            market_iv = float(md.get("volatility") or 0)

            quotes.append(OptionQuote(
                symbol=sym,
                underlying=underlying.upper(),
                strike=strike,
                expiry=expiry,
                option_type=option_type,
                bid=bid,
                ask=ask,
                mid=mid_val,
                market_iv=market_iv,
                underlying_price=stock_price,
            ))

        return quotes

    async def _get_stock_price(self, symbol: str) -> float:
        resp = await self._http.get(
            "/market-data/by-type",
            params={"equity": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        if not items:
            raise ValueError(f"No market data for {symbol}")
        item = items[0]
        return float(item.get("last") or item.get("mark") or item.get("prev-close") or 0)

    async def _get_option_chain(self, symbol: str) -> list[dict]:
        """Get all active options for the symbol."""
        resp = await self._http.get(f"/option-chains/{symbol}")
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        return [i for i in items if i.get("active", True)]

    async def _get_market_data_batched(self, symbols: list[str]) -> dict[str, dict]:
        """Get bid/ask/IV/greeks for option symbols in parallel batches."""
        result = {}
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def fetch_batch(batch):
            async with sem:
                resp = await self._http.get(
                    "/market-data/by-type",
                    params={"equity-option": ",".join(batch)},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("data", {}).get("items", []):
                        result[item["symbol"]] = item
                else:
                    logger.warning(f"Market data batch failed: {resp.status_code}")

        tasks = []
        for i in range(0, len(symbols), BATCH_SIZE):
            batch = symbols[i:i + BATCH_SIZE]
            tasks.append(fetch_batch(batch))

        await asyncio.gather(*tasks)
        return result

    async def fetch_market_metrics(self, symbol: str) -> dict | None:
        """Fetch IV rank, IV percentile, liquidity from /market-metrics."""
        resp = await self._http.get(
            "/market-metrics",
            params={"symbols": symbol.upper()},
        )
        if resp.status_code != 200:
            logger.warning(f"Market metrics failed for {symbol}: {resp.status_code}")
            return None
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        if not items:
            return None
        item = items[0]
        return {
            "iv_index": float(item["implied-volatility-index"]) if item.get("implied-volatility-index") else None,
            "iv_index_5d_change": float(item["implied-volatility-index-5-day-change"]) if item.get("implied-volatility-index-5-day-change") else None,
            "iv_rank": float(item["implied-volatility-rank"]) if item.get("implied-volatility-rank") else None,
            "iv_percentile": float(item["implied-volatility-percentile"]) if item.get("implied-volatility-percentile") else None,
            "liquidity": float(item["liquidity"]) if item.get("liquidity") else None,
            "liquidity_rank": float(item["liquidity-rank"]) if item.get("liquidity-rank") else None,
            "liquidity_rating": int(item["liquidity-rating"]) if item.get("liquidity-rating") else None,
            "expiry_ivs": [
                {
                    "expiry": e.get("expiration-date", ""),
                    "settlement_type": e.get("settlement-type"),
                    "option_chain_type": e.get("option-chain-type"),
                    "iv": float(e["implied-volatility"]) if e.get("implied-volatility") else None,
                }
                for e in item.get("option-expiration-implied-volatilities", [])
            ],
        }

    async def fetch_earnings(self, symbol: str) -> list[dict]:
        """Fetch historical earnings reports."""
        resp = await self._http.get(
            f"/market-metrics/historic-corporate-events/earnings-reports/{symbol.upper()}",
        )
        if resp.status_code != 200:
            logger.warning(f"Earnings fetch failed for {symbol}: {resp.status_code}")
            return []
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        return [
            {
                "occurred_date": item["occurred-date"],
                "eps": float(item["eps"]) if item.get("eps") is not None else None,
            }
            for item in items
            if item.get("occurred-date")
        ]

    async def fetch_dividends(self, symbol: str) -> list[dict]:
        """Fetch historical dividend data."""
        resp = await self._http.get(
            f"/market-metrics/historic-corporate-events/dividends/{symbol.upper()}",
        )
        if resp.status_code != 200:
            logger.warning(f"Dividends fetch failed for {symbol}: {resp.status_code}")
            return []
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        return [
            {
                "occurred_date": item["occurred-date"],
                "amount": float(item["amount"]) if item.get("amount") is not None else None,
            }
            for item in items
            if item.get("occurred-date")
        ]

    async def close(self):
        await self._http.aclose()
