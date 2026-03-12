"""Tests for the fetch pipeline (POST /api/fetch/{underlying})."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings, get_settings
from app.main import app
from app.models import Alert, Contract, Snapshot, Underlying
from app.services.deribit import OptionQuote
from app.services.tastytrade import OptionQuote as TastyOptionQuote


def _make_chain(underlying_price=75000.0):
    """Create a minimal realistic option chain for testing."""
    return [
        OptionQuote(
            symbol="BTC-27MAR26-70000-C",
            underlying="BTC",
            strike=70000.0,
            expiry=date(2026, 3, 27),
            option_type="C",
            bid=6000.0,
            ask=6100.0,
            mid=6050.0,
            market_iv=0.55,
            underlying_price=underlying_price,
            mark_price=6050.0,
        ),
        OptionQuote(
            symbol="BTC-27MAR26-75000-C",
            underlying="BTC",
            strike=75000.0,
            expiry=date(2026, 3, 27),
            option_type="C",
            bid=3000.0,
            ask=3050.0,
            mid=3025.0,
            market_iv=0.50,
            underlying_price=underlying_price,
            mark_price=3025.0,
        ),
        OptionQuote(
            symbol="BTC-27MAR26-80000-C",
            underlying="BTC",
            strike=80000.0,
            expiry=date(2026, 3, 27),
            option_type="C",
            bid=1200.0,
            ask=1250.0,
            mid=1225.0,
            market_iv=0.48,
            underlying_price=underlying_price,
            mark_price=1225.0,
        ),
        OptionQuote(
            symbol="BTC-27MAR26-85000-C",
            underlying="BTC",
            strike=85000.0,
            expiry=date(2026, 3, 27),
            option_type="C",
            bid=400.0,
            ask=450.0,
            mid=425.0,
            market_iv=0.52,
            underlying_price=underlying_price,
            mark_price=425.0,
        ),
        OptionQuote(
            symbol="BTC-27MAR26-90000-C",
            underlying="BTC",
            strike=90000.0,
            expiry=date(2026, 3, 27),
            option_type="C",
            bid=100.0,
            ask=120.0,
            mid=110.0,
            market_iv=0.60,
            underlying_price=underlying_price,
            mark_price=110.0,
        ),
    ]


class TestFetchEndpoint:
    def test_fetch_invalid_underlying(self, client):
        resp = client.post("/api/fetch/123BAD!")
        assert resp.status_code == 400
        assert "Invalid symbol" in resp.json()["detail"]

    def test_fetch_tastytrade_no_token(self, client):
        resp = client.post("/api/fetch/SPY")
        assert resp.status_code == 503
        assert "Tastytrade refresh token not configured" in resp.json()["detail"]

    def test_fetch_creates_snapshots(self, client, db):
        """Full pipeline: mock Deribit, verify snapshots + contracts created."""
        chain = _make_chain()

        with patch("app.routers.fetch.DeribitClient") as MockClient, \
             patch("app.routers.fetch.get_risk_free_rate", new_callable=AsyncMock, return_value=0.05):
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=chain)
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 200
        data = resp.json()
        assert data["underlying"] == "BTC"
        assert data["snapshots"] == 5
        assert data["source"] == "deribit"

        # Verify contracts were created
        contracts = db.query(Contract).filter(Contract.underlying == "BTC").all()
        assert len(contracts) == 5

        # Verify snapshots were created with greeks
        snapshots = db.query(Snapshot).all()
        assert len(snapshots) == 5
        for snap in snapshots:
            assert snap.market_iv is not None
            assert snap.bid is not None

    def test_fetch_empty_chain_returns_404(self, client):
        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 404

    def test_fetch_deribit_error_returns_502(self, client):
        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(side_effect=ConnectionError("timeout"))
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 502
        assert "Failed to fetch data from deribit" in resp.json()["detail"]

    def test_fetch_net_edge_in_dollars(self, client, db):
        """Verify net_edge is computed in dollar terms (not vol terms)."""
        chain = _make_chain()

        with patch("app.routers.fetch.DeribitClient") as MockClient, \
             patch("app.routers.fetch.get_risk_free_rate", new_callable=AsyncMock, return_value=0.05):
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=chain)
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 200

        # Check that net_edge values are in dollar terms (not tiny vol decimals)
        snapshots = db.query(Snapshot).filter(Snapshot.net_edge.isnot(None)).all()
        for snap in snapshots:
            net_edge = float(snap.net_edge)
            # net_edge should be abs(deviation) * 100 * vega - half_spread
            # For BTC options with vega ~50-100 and deviation ~0.02-0.10,
            # price_edge should be in hundreds of dollars range
            # net_edge can be negative (spread > edge), but should NOT be tiny decimals
            if float(snap.vega) > 10 and abs(float(snap.deviation)) > 0.01:
                assert abs(net_edge) > 1.0, (
                    f"net_edge={net_edge} too small — likely still in vol terms"
                )


def _make_futures_chain():
    """Create a minimal futures option chain for testing."""
    return [
        TastyOptionQuote(
            symbol="./ESM6C5500",
            underlying="/ES",
            strike=5500.0,
            expiry=date(2026, 6, 19),
            option_type="C",
            bid=50.0,
            ask=51.0,
            mid=50.5,
            market_iv=0.18,
            underlying_price=5500.0,
        ),
        TastyOptionQuote(
            symbol="./ESM6P5500",
            underlying="/ES",
            strike=5500.0,
            expiry=date(2026, 6, 19),
            option_type="P",
            bid=48.0,
            ask=49.0,
            mid=48.5,
            market_iv=0.19,
            underlying_price=5500.0,
        ),
    ]


class TestFetchFutures:
    @pytest.fixture(autouse=True)
    def _override_settings(self):
        """Override settings to include a fake tastytrade refresh token."""
        mock_settings = MagicMock(spec=Settings)
        mock_settings.deribit_client_id = ""
        mock_settings.deribit_client_secret = ""
        mock_settings.tastytrade_client_id = "test-id"
        mock_settings.tastytrade_client_secret = "test-secret"
        mock_settings.tastytrade_refresh_token = "test-refresh"
        mock_settings.fred_api_key = ""
        mock_settings.vol_threshold = 2.0
        app.dependency_overrides[get_settings] = lambda: mock_settings
        yield
        app.dependency_overrides.pop(get_settings, None)

    def test_fetch_futures_creates_snapshots(self, client, db):
        """Futures symbol /ES should route to futures chain."""
        chain = _make_futures_chain()

        with patch("app.routers.fetch.TastytradeClient") as MockClient, \
             patch("app.routers.fetch.get_risk_free_rate", new_callable=AsyncMock, return_value=0.05):
            instance = MockClient.return_value
            instance.fetch_futures_chain = AsyncMock(return_value=chain)
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/%2FES")

        assert resp.status_code == 200
        data = resp.json()
        assert data["underlying"] == "/ES"
        assert data["source"] == "tastytrade"
        assert data["snapshots"] == 2

        # Verify underlying record created with market=futures
        u = db.query(Underlying).filter(Underlying.symbol == "/ES").first()
        assert u is not None
        assert u.market == "futures"

    def test_fetch_futures_empty_chain(self, client, db):
        """Empty futures chain returns 404."""
        with patch("app.routers.fetch.TastytradeClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_futures_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/%2FES")

        assert resp.status_code == 404
