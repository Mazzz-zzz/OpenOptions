"""Tests for Tastytrade REST client."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tastytrade import TastytradeClient, OptionQuote


class TestTastytradeParsing:
    def setup_method(self):
        self.client = TastytradeClient(
            client_id="test-id",
            client_secret="test-secret",
            refresh_token="test-refresh",
        )

    def _mock_response(self, json_data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.raise_for_status = MagicMock()
        resp.status_code = status_code
        return resp

    @pytest.mark.asyncio
    async def test_ensure_token(self):
        """OAuth token exchange sets Authorization header."""
        resp = self._mock_response({
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 86400,
        })
        with patch.object(self.client._http, "post", AsyncMock(return_value=resp)):
            await self.client._ensure_token()

        assert self.client._http.headers["Authorization"] == "Bearer new-access-token"
        assert self.client.refresh_token == "new-refresh-token"

    @pytest.mark.asyncio
    async def test_get_stock_price(self):
        resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "SPY", "last": "500.25", "bid": "500.20", "ask": "500.30"}
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            price = await self.client._get_stock_price("SPY")

        assert price == 500.25

    @pytest.mark.asyncio
    async def test_get_stock_price_no_data(self):
        resp = self._mock_response({"data": {"items": []}})
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            with pytest.raises(ValueError, match="No market data"):
                await self.client._get_stock_price("SPY")

    @pytest.mark.asyncio
    async def test_get_option_chain(self):
        resp = self._mock_response({
            "data": {
                "items": [
                    {
                        "symbol": "SPY   260320C00500000",
                        "strike-price": "500.0",
                        "expiration-date": "2026-03-20",
                        "option-type": "C",
                        "active": True,
                    },
                    {
                        "symbol": "SPY   260320C00600000",
                        "strike-price": "600.0",
                        "expiration-date": "2026-03-20",
                        "option-type": "C",
                        "active": False,
                    },
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            options = await self.client._get_option_chain("SPY")

        assert len(options) == 1
        assert options[0]["symbol"] == "SPY   260320C00500000"

    @pytest.mark.asyncio
    async def test_get_market_data_batched(self):
        resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "SPY   260320C00500000", "bid": "15.50", "ask": "16.00", "volatility": "0.22"},
                    {"symbol": "SPY   260320P00500000", "bid": "12.00", "ask": "12.50", "volatility": "0.23"},
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            result = await self.client._get_market_data_batched([
                "SPY   260320C00500000",
                "SPY   260320P00500000",
            ])

        assert len(result) == 2
        assert result["SPY   260320C00500000"]["bid"] == "15.50"

    @pytest.mark.asyncio
    async def test_fetch_chain_filters_zero_bid_ask(self):
        """Options with zero bid and ask should be filtered out."""
        future_expiry = (date.today() + timedelta(days=14)).isoformat()
        token_resp = self._mock_response({
            "access_token": "tok", "expires_in": 3600,
        })
        stock_resp = self._mock_response({
            "data": {"items": [{"symbol": "SPY", "last": "500.0"}]}
        })
        chain_resp = self._mock_response({
            "data": {
                "items": [
                    {
                        "symbol": "SPY   260320C00500000",
                        "strike-price": "500.0",
                        "expiration-date": future_expiry,
                        "option-type": "C",
                        "active": True,
                    },
                    {
                        "symbol": "SPY   260320C00700000",
                        "strike-price": "700.0",
                        "expiration-date": future_expiry,
                        "option-type": "C",
                        "active": True,
                    },
                ]
            }
        })
        market_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "SPY   260320C00500000", "bid": "15.50", "ask": "16.00", "volatility": "0.22"},
                    {"symbol": "SPY   260320C00700000", "bid": "0", "ask": "0", "volatility": "0"},
                ]
            }
        })

        async def mock_get(url, **kwargs):
            params = kwargs.get("params", {})
            if "market-data" in url and "equity" in params:
                return stock_resp
            if "option-chains" in url:
                return chain_resp
            return market_resp

        with patch.object(self.client._http, "post", AsyncMock(return_value=token_resp)):
            with patch.object(self.client._http, "get", AsyncMock(side_effect=mock_get)):
                quotes = await self.client.fetch_chain("SPY")

        # Zero bid/ask filtered, 700 strike filtered by moneyness (>130% of 500)
        assert len(quotes) == 1
        assert quotes[0].strike == 500.0
        assert quotes[0].option_type == "C"
        assert quotes[0].underlying_price == 500.0
        assert quotes[0].bid == 15.50
        assert quotes[0].ask == 16.00
        assert quotes[0].market_iv == 0.22

    @pytest.mark.asyncio
    async def test_fetch_chain_uses_tastytrade_iv(self):
        """Market IV should come from Tastytrade volatility field."""
        future_expiry = (date.today() + timedelta(days=14)).isoformat()
        token_resp = self._mock_response({
            "access_token": "tok", "expires_in": 3600,
        })
        stock_resp = self._mock_response({
            "data": {"items": [{"symbol": "SPY", "last": "500.0"}]}
        })
        chain_resp = self._mock_response({
            "data": {
                "items": [
                    {
                        "symbol": "SPY   260320C00500000",
                        "strike-price": "500.0",
                        "expiration-date": future_expiry,
                        "option-type": "C",
                        "active": True,
                    },
                ]
            }
        })
        market_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "SPY   260320C00500000", "bid": "15.50", "ask": "16.00", "volatility": "0.208442"},
                ]
            }
        })

        async def mock_get(url, **kwargs):
            params = kwargs.get("params", {})
            if "market-data" in url and "equity" in params:
                return stock_resp
            if "option-chains" in url:
                return chain_resp
            return market_resp

        with patch.object(self.client._http, "post", AsyncMock(return_value=token_resp)):
            with patch.object(self.client._http, "get", AsyncMock(side_effect=mock_get)):
                quotes = await self.client.fetch_chain("SPY")

        assert len(quotes) == 1
        assert abs(quotes[0].market_iv - 0.208442) < 1e-6

    @pytest.mark.asyncio
    async def test_market_data_batch_failure_skips(self):
        """Failed market data batch should log warning, not crash."""
        resp = self._mock_response({}, status_code=500)
        resp.status_code = 500
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            result = await self.client._get_market_data_batched(["SYM1"])

        assert result == {}
