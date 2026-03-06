"""Deribit REST client for crypto options chain data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE_URL = "https://www.deribit.com/api/v2"


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
    market_iv: float  # implied vol as decimal (e.g. 0.65 = 65%)
    underlying_price: float
    mark_price: float


class DeribitClient:
    def __init__(self, client_id: str = "", client_secret: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def fetch_chain(self, underlying: str) -> list[OptionQuote]:
        """Fetch full options chain for a currency (BTC, ETH).

        Uses /public/get_book_summary_by_currency to get all contracts
        in a single call, avoiding per-contract rate limit issues.
        """
        currency = underlying.upper()
        resp = await self._http.get(
            "/public/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
        )
        resp.raise_for_status()
        data = resp.json()["result"]

        quotes = []
        for item in data:
            # Skip instruments with no bid/ask
            if item.get("bid_price") is None or item.get("ask_price") is None:
                continue
            if item["bid_price"] <= 0 and item["ask_price"] <= 0:
                continue

            quote = self._parse_instrument(item, currency)
            if quote:
                quotes.append(quote)

        return quotes

    def _parse_instrument(self, item: dict, currency: str) -> OptionQuote | None:
        """Parse a Deribit book summary into an OptionQuote."""
        instrument_name = item["instrument_name"]
        # Format: BTC-27JUN25-100000-C
        parts = instrument_name.split("-")
        if len(parts) != 4:
            return None

        try:
            expiry = datetime.strptime(parts[1], "%d%b%y").date()
        except ValueError:
            return None

        strike = float(parts[2])
        option_type = parts[3]  # 'C' or 'P'

        underlying_price = item.get("underlying_price", 0)
        if underlying_price <= 0:
            return None

        # Deribit prices are in BTC terms; convert to USD
        bid = item["bid_price"] * underlying_price if item["bid_price"] else 0
        ask = item["ask_price"] * underlying_price if item["ask_price"] else 0
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
        mark = item.get("mark_price", 0) * underlying_price

        # IV from Deribit is already annualized, as a fraction
        market_iv = item.get("mark_iv", 0)
        if market_iv:
            market_iv = market_iv / 100.0  # convert from percentage

        return OptionQuote(
            symbol=instrument_name,
            underlying=currency,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
            bid=bid,
            ask=ask,
            mid=mid,
            market_iv=market_iv,
            underlying_price=underlying_price,
            mark_price=mark,
        )

    async def close(self):
        await self._http.aclose()
