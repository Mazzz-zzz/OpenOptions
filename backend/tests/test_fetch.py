"""Tests for the fetch pipeline (POST /api/fetch/{underlying})."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Alert, Contract, Snapshot
from app.services.deribit import OptionQuote


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
