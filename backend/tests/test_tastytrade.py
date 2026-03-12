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

        # 700 strike has bid=0, ask=0 — filtered out by zero bid/ask check
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

    @pytest.mark.asyncio
    async def test_fetch_market_metrics(self):
        """Market metrics returns IV rank, percentile, liquidity."""
        resp = self._mock_response({
            "data": {
                "items": [{
                    "symbol": "SPY",
                    "implied-volatility-index": "0.1842",
                    "implied-volatility-index-5-day-change": "-0.0053",
                    "implied-volatility-rank": "32.5",
                    "implied-volatility-percentile": "28.0",
                    "liquidity": "1500.0",
                    "liquidity-rank": "950.0",
                    "liquidity-rating": "4",
                    "option-expiration-implied-volatilities": [
                        {
                            "expiration-date": "2026-03-20",
                            "settlement-type": "PM",
                            "option-chain-type": "Standard",
                            "implied-volatility": "0.1952",
                        },
                    ],
                }]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            metrics = await self.client.fetch_market_metrics("SPY")

        assert metrics is not None
        assert abs(metrics["iv_index"] - 0.1842) < 1e-6
        assert abs(metrics["iv_index_5d_change"] - (-0.0053)) < 1e-6
        assert abs(metrics["iv_rank"] - 32.5) < 0.1
        assert abs(metrics["iv_percentile"] - 28.0) < 0.1
        assert metrics["liquidity_rating"] == 4
        assert len(metrics["expiry_ivs"]) == 1
        assert abs(metrics["expiry_ivs"][0]["iv"] - 0.1952) < 1e-6

    @pytest.mark.asyncio
    async def test_fetch_market_metrics_failure_returns_none(self):
        resp = self._mock_response({}, status_code=500)
        resp.status_code = 500
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            result = await self.client.fetch_market_metrics("SPY")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_earnings(self):
        resp = self._mock_response({
            "data": {
                "items": [
                    {"occurred-date": "2026-01-15", "eps": "2.35"},
                    {"occurred-date": "2025-10-15", "eps": "-0.10"},
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            earnings = await self.client.fetch_earnings("AAPL")

        assert len(earnings) == 2
        assert earnings[0]["occurred_date"] == "2026-01-15"
        assert abs(earnings[0]["eps"] - 2.35) < 0.01
        assert abs(earnings[1]["eps"] - (-0.10)) < 0.01

    @pytest.mark.asyncio
    async def test_fetch_earnings_failure_returns_empty(self):
        resp = self._mock_response({}, status_code=404)
        resp.status_code = 404
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            result = await self.client.fetch_earnings("XYZ")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_dividends(self):
        resp = self._mock_response({
            "data": {
                "items": [
                    {"occurred-date": "2026-02-10", "amount": "0.2400"},
                    {"occurred-date": "2025-11-10", "amount": "0.2300"},
                ]
            }
        })
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            dividends = await self.client.fetch_dividends("AAPL")

        assert len(dividends) == 2
        assert dividends[0]["occurred_date"] == "2026-02-10"
        assert abs(dividends[0]["amount"] - 0.24) < 0.001

    @pytest.mark.asyncio
    async def test_fetch_dividends_failure_returns_empty(self):
        resp = self._mock_response({}, status_code=500)
        resp.status_code = 500
        with patch.object(self.client._http, "get", AsyncMock(return_value=resp)):
            result = await self.client.fetch_dividends("XYZ")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_futures_chain(self):
        """Futures option chain should parse nested response structure."""
        future_expiry = (date.today() + timedelta(days=14)).isoformat()
        token_resp = self._mock_response({"access_token": "tok", "expires_in": 3600})

        # Futures instruments response
        instruments_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "/ESM6", "product-code": "ES", "is-closing-only": False},
                ]
            }
        })

        # Futures price response
        futures_md_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "/ESM6", "last": "5500.0", "mark": "5500.25"}
                ]
            }
        })

        # Nested chain response (real API structure: option-chains[].expirations[].strikes[])
        chain_resp = self._mock_response({
            "data": {
                "futures": [{"symbol": "/ESM6"}],
                "option-chains": [{
                    "underlying-symbol": "/ES",
                    "root-symbol": "/ES",
                    "expirations": [{
                        "underlying-symbol": "/ESM6",
                        "expiration-date": future_expiry,
                        "strikes": [{
                            "strike-price": "5500.0",
                            "call": "./ESM6C5500",
                            "put": "./ESM6P5500",
                        }],
                    }],
                }]
            }
        })

        # Market data for futures options
        option_md_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "./ESM6C5500", "bid": "50.0", "ask": "51.0", "volatility": "0.18"},
                    {"symbol": "./ESM6P5500", "bid": "48.0", "ask": "49.0", "volatility": "0.19"},
                ]
            }
        })

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            params = kwargs.get("params", {})
            if "instruments/futures" in url:
                return instruments_resp
            if "futures-option-chains" in url:
                return chain_resp
            if "market-data" in url:
                if "future-option" in params:
                    return option_md_resp
                if "future" in params:
                    return futures_md_resp
            return option_md_resp

        with patch.object(self.client._http, "post", AsyncMock(return_value=token_resp)):
            with patch.object(self.client._http, "get", AsyncMock(side_effect=mock_get)):
                quotes = await self.client.fetch_futures_chain("ES")

        assert len(quotes) == 2
        assert quotes[0].underlying == "/ES"
        assert quotes[0].underlying_price == 5500.0
        assert quotes[0].strike == 5500.0
        types = {q.option_type for q in quotes}
        assert "C" in types
        assert "P" in types

    @pytest.mark.asyncio
    async def test_fetch_futures_chain_empty(self):
        """Empty futures chain should return empty list."""
        token_resp = self._mock_response({"access_token": "tok", "expires_in": 3600})
        instruments_resp = self._mock_response({
            "data": {"items": [{"symbol": "/ESM6", "is-closing-only": False, "product-code": "ES"}]}
        })
        futures_md_resp = self._mock_response({
            "data": {"items": [{"symbol": "/ESM6", "last": "5500.0"}]}
        })
        chain_resp = self._mock_response({"data": {"futures": [], "option-chains": []}})

        async def mock_get(url, **kwargs):
            params = kwargs.get("params", {})
            if "instruments/futures" in url:
                return instruments_resp
            if "futures-option-chains" in url:
                return chain_resp
            if "market-data" in url and "future" in params:
                return futures_md_resp
            return self._mock_response({"data": {"items": []}})

        with patch.object(self.client._http, "post", AsyncMock(return_value=token_resp)):
            with patch.object(self.client._http, "get", AsyncMock(side_effect=mock_get)):
                quotes = await self.client.fetch_futures_chain("ES")

        assert quotes == []

    @pytest.mark.asyncio
    async def test_fetch_chain_no_expiry_filter(self):
        """After removing MAX_DTE, far-dated contracts should be included."""
        far_expiry = (date.today() + timedelta(days=365)).isoformat()
        near_expiry = (date.today() + timedelta(days=14)).isoformat()
        token_resp = self._mock_response({"access_token": "tok", "expires_in": 3600})
        stock_resp = self._mock_response({"data": {"items": [{"symbol": "SPY", "last": "500.0"}]}})
        chain_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "NEAR", "strike-price": "500.0", "expiration-date": near_expiry, "option-type": "C", "active": True},
                    {"symbol": "FAR", "strike-price": "500.0", "expiration-date": far_expiry, "option-type": "C", "active": True},
                ]
            }
        })
        market_resp = self._mock_response({
            "data": {
                "items": [
                    {"symbol": "NEAR", "bid": "10.0", "ask": "11.0", "volatility": "0.20"},
                    {"symbol": "FAR", "bid": "25.0", "ask": "26.0", "volatility": "0.25"},
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

        assert len(quotes) == 2
        symbols = {q.symbol for q in quotes}
        assert "NEAR" in symbols
        assert "FAR" in symbols
