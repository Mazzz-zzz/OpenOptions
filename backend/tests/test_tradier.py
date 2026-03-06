"""Tests for Tradier REST client."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tradier import TradierClient, OptionQuote


class TestTradierParsing:
    def setup_method(self):
        self.client = TradierClient(token="test-token")

    def _mock_response(self, json_data):
        """Create a mock httpx response with sync .json() and .raise_for_status()."""
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        return resp

    @pytest.mark.asyncio
    async def test_get_expirations(self):
        resp = self._mock_response({
            "expirations": {
                "date": ["2026-03-20", "2026-04-17", "2026-06-19"]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            expirations = await self.client._get_expirations("SPY")

        assert len(expirations) == 3
        assert expirations[0] == date(2026, 3, 20)

    @pytest.mark.asyncio
    async def test_get_expirations_single_date(self):
        """Tradier returns a string instead of list for single expiration."""
        resp = self._mock_response({
            "expirations": {"date": "2026-03-20"}
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            expirations = await self.client._get_expirations("SPY")

        assert len(expirations) == 1

    @pytest.mark.asyncio
    async def test_get_chain_for_expiry(self):
        resp = self._mock_response({
            "options": {
                "option": [
                    {
                        "symbol": "SPY260320C00500000",
                        "option_type": "call",
                        "strike": 500.0,
                        "bid": 15.50,
                        "ask": 16.00,
                        "greeks": {"mid_iv": 0.22},
                    },
                    {
                        "symbol": "SPY260320P00500000",
                        "option_type": "put",
                        "strike": 500.0,
                        "bid": 12.00,
                        "ask": 12.50,
                        "greeks": {"mid_iv": 0.23},
                    },
                    {
                        "symbol": "SPY260320C00600000",
                        "option_type": "call",
                        "strike": 600.0,
                        "bid": 0,
                        "ask": 0,
                        "greeks": None,
                    },
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            quotes = await self.client._get_chain_for_expiry("SPY", date(2026, 3, 20), 500.0)

        # Third option has bid=0 and ask=0, should be filtered
        assert len(quotes) == 2
        assert quotes[0].option_type == "C"
        assert quotes[1].option_type == "P"
        assert quotes[0].market_iv == 0.22
        assert quotes[0].underlying_price == 500.0

    @pytest.mark.asyncio
    async def test_get_chain_single_option(self):
        """Tradier returns a dict instead of list for single option."""
        resp = self._mock_response({
            "options": {
                "option": {
                    "symbol": "SPY260320C00500000",
                    "option_type": "call",
                    "strike": 500.0,
                    "bid": 15.50,
                    "ask": 16.00,
                    "greeks": {"mid_iv": 0.22},
                }
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            quotes = await self.client._get_chain_for_expiry("SPY", date(2026, 3, 20), 500.0)

        assert len(quotes) == 1

    @pytest.mark.asyncio
    async def test_get_chain_null_greeks(self):
        """Options with null greeks should get market_iv=0."""
        resp = self._mock_response({
            "options": {
                "option": [
                    {
                        "symbol": "SPY260320C00500000",
                        "option_type": "call",
                        "strike": 500.0,
                        "bid": 15.50,
                        "ask": 16.00,
                        "greeks": None,
                    },
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            quotes = await self.client._get_chain_for_expiry("SPY", date(2026, 3, 20), 500.0)

        assert len(quotes) == 1
        assert quotes[0].market_iv == 0.0
