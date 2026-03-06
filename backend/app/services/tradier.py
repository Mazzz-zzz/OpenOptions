"""Tradier REST client for US equity options chain data."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE_URL = "https://sandbox.tradier.com/v1"  # Use production URL with paid plan


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


class TradierClient:
    def __init__(self, token: str = ""):
        self.token = token
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    async def fetch_chain(self, underlying: str) -> list[OptionQuote]:
        """Fetch full options chain for a US equity symbol."""
        # Get current stock price
        stock_price = await self._get_stock_price(underlying)

        # Get available expiration dates
        expirations = await self._get_expirations(underlying)

        quotes = []
        for expiry in expirations:
            chain = await self._get_chain_for_expiry(underlying, expiry, stock_price)
            quotes.extend(chain)

        return quotes

    async def _get_stock_price(self, symbol: str) -> float:
        resp = await self._http.get(
            "/markets/quotes",
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        quote = data["quotes"]["quote"]
        if isinstance(quote, list):
            quote = quote[0]
        return float(quote.get("last", quote.get("close", 0)))

    async def _get_expirations(self, symbol: str) -> list[date]:
        resp = await self._http.get(
            "/markets/options/expirations",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        dates_raw = data.get("expirations", {}).get("date", [])
        if isinstance(dates_raw, str):
            dates_raw = [dates_raw]
        return [datetime.strptime(d, "%Y-%m-%d").date() for d in dates_raw]

    async def _get_chain_for_expiry(
        self, symbol: str, expiry: date, stock_price: float
    ) -> list[OptionQuote]:
        resp = await self._http.get(
            "/markets/options/chains",
            params={
                "symbol": symbol,
                "expiration": expiry.isoformat(),
                "greeks": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        options = data.get("options", {}).get("option", [])
        if isinstance(options, dict):
            options = [options]

        quotes = []
        for opt in options:
            bid = float(opt.get("bid", 0) or 0)
            ask = float(opt.get("ask", 0) or 0)
            if bid <= 0 and ask <= 0:
                continue

            mid = (bid + ask) / 2

            # Tradier provides greeks including mid_iv
            greeks = opt.get("greeks", {}) or {}
            market_iv = float(greeks.get("mid_iv", 0) or 0)

            option_type = "C" if opt["option_type"] == "call" else "P"

            quotes.append(
                OptionQuote(
                    symbol=opt["symbol"],
                    underlying=symbol.upper(),
                    strike=float(opt["strike"]),
                    expiry=expiry,
                    option_type=option_type,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    market_iv=market_iv,
                    underlying_price=stock_price,
                )
            )

        return quotes

    async def close(self):
        await self._http.aclose()
