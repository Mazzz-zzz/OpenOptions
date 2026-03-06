"""Tests for Deribit REST client."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.deribit import DeribitClient, OptionQuote


class TestDeribitParsing:
    def setup_method(self):
        self.client = DeribitClient()

    def test_parse_valid_instrument(self):
        item = {
            "instrument_name": "BTC-27JUN25-100000-C",
            "bid_price": 0.05,
            "ask_price": 0.06,
            "mark_price": 0.055,
            "mark_iv": 65.0,
            "underlying_price": 90000.0,
        }
        quote = self.client._parse_instrument(item, "BTC")
        assert quote is not None
        assert quote.symbol == "BTC-27JUN25-100000-C"
        assert quote.underlying == "BTC"
        assert quote.strike == 100000.0
        assert quote.expiry == date(2025, 6, 27)
        assert quote.option_type == "C"
        assert quote.bid == 0.05 * 90000.0
        assert quote.ask == 0.06 * 90000.0
        assert quote.market_iv == 0.65

    def test_parse_put_option(self):
        item = {
            "instrument_name": "ETH-28MAR25-3000-P",
            "bid_price": 0.1,
            "ask_price": 0.12,
            "mark_price": 0.11,
            "mark_iv": 80.0,
            "underlying_price": 3500.0,
        }
        quote = self.client._parse_instrument(item, "ETH")
        assert quote is not None
        assert quote.option_type == "P"
        assert quote.market_iv == 0.80

    def test_parse_invalid_instrument_name(self):
        item = {
            "instrument_name": "BTC-PERPETUAL",
            "bid_price": 0.05,
            "ask_price": 0.06,
            "underlying_price": 90000.0,
        }
        quote = self.client._parse_instrument(item, "BTC")
        assert quote is None

    def test_parse_zero_underlying_price(self):
        item = {
            "instrument_name": "BTC-27JUN25-100000-C",
            "bid_price": 0.05,
            "ask_price": 0.06,
            "underlying_price": 0,
        }
        quote = self.client._parse_instrument(item, "BTC")
        assert quote is None

    def test_parse_invalid_date(self):
        item = {
            "instrument_name": "BTC-INVALID-100000-C",
            "bid_price": 0.05,
            "ask_price": 0.06,
            "underlying_price": 90000.0,
        }
        quote = self.client._parse_instrument(item, "BTC")
        assert quote is None

    def test_parse_zero_iv(self):
        item = {
            "instrument_name": "BTC-27JUN25-100000-C",
            "bid_price": 0.05,
            "ask_price": 0.06,
            "mark_price": 0.055,
            "mark_iv": 0,
            "underlying_price": 90000.0,
        }
        quote = self.client._parse_instrument(item, "BTC")
        assert quote is not None
        assert quote.market_iv == 0

    @pytest.mark.asyncio
    async def test_fetch_chain_filters_invalid(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "instrument_name": "BTC-27JUN25-100000-C",
                    "bid_price": 0.05,
                    "ask_price": 0.06,
                    "mark_price": 0.055,
                    "mark_iv": 65.0,
                    "underlying_price": 90000.0,
                },
                {
                    "instrument_name": "BTC-PERPETUAL",
                    "bid_price": 0.05,
                    "ask_price": 0.06,
                    "underlying_price": 90000.0,
                },
                {
                    "instrument_name": "BTC-27JUN25-200000-P",
                    "bid_price": None,
                    "ask_price": None,
                    "underlying_price": 90000.0,
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()

        # httpx.AsyncClient.get is async, so mock it as AsyncMock returning sync response
        mock_get = AsyncMock(return_value=mock_response)

        with patch.object(self.client._http, "get", mock_get):
            quotes = await self.client.fetch_chain("BTC")

        assert len(quotes) == 1
        assert quotes[0].symbol == "BTC-27JUN25-100000-C"
