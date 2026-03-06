"""Tests for the underlyings tracking endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.models import Underlying
from app.services.deribit import OptionQuote


def _make_underlying(db, symbol="BTC", last_fetched_at=None):
    u = Underlying(
        symbol=symbol,
        market="crypto" if symbol in ("BTC", "ETH") else "equity",
        source="deribit" if symbol in ("BTC", "ETH") else "tastytrade",
        last_fetched_at=last_fetched_at,
        last_spot=75000.0 if symbol == "BTC" else 100.0,
        last_snapshot_count=5,
        last_alert_count=1,
    )
    db.add(u)
    db.flush()
    return u


class TestListUnderlyings:
    def test_list_empty(self, client):
        resp = client.get("/api/underlyings")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_returns_tracked(self, client, db):
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=10))
        _make_underlying(db, "SPY", datetime.now(timezone.utc) - timedelta(minutes=3))
        resp = client.get("/api/underlyings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        # SPY fetched more recently, should be first
        assert data[0]["symbol"] == "SPY"
        assert data[1]["symbol"] == "BTC"

    def test_list_hides_inactive(self, client, db):
        u = _make_underlying(db, "BTC")
        u.is_active = False
        db.flush()
        resp = client.get("/api/underlyings")
        assert resp.json()["data"] == []

    def test_list_shows_inactive_when_requested(self, client, db):
        u = _make_underlying(db, "BTC")
        u.is_active = False
        db.flush()
        resp = client.get("/api/underlyings?active_only=false")
        assert len(resp.json()["data"]) == 1

    def test_cooldown_flag(self, client, db):
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=1))
        _make_underlying(db, "SPY", datetime.now(timezone.utc) - timedelta(minutes=10))
        resp = client.get("/api/underlyings")
        data = {item["symbol"]: item for item in resp.json()["data"]}
        assert data["BTC"]["on_cooldown"] is True
        assert data["SPY"]["on_cooldown"] is False


class TestRemoveUnderlying:
    def test_remove_deactivates(self, client, db):
        _make_underlying(db, "BTC")
        resp = client.delete("/api/underlyings/BTC")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        row = db.query(Underlying).filter(Underlying.symbol == "BTC").first()
        assert row.is_active is False

    def test_remove_not_found(self, client):
        resp = client.delete("/api/underlyings/NOPE")
        assert resp.status_code == 404


class TestFetchCooldown:
    def test_cooldown_blocks_refetch(self, client, db):
        """Fetching the same symbol within cooldown returns 429."""
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=2))

        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 429
        assert "recently" in resp.json()["detail"]

    def test_cooldown_allows_after_expiry(self, client, db):
        """Fetching after cooldown expires should proceed normally."""
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=10))

        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        # Empty chain → 404 (not 429)
        assert resp.status_code == 404

    def test_force_bypasses_cooldown(self, client, db):
        """force=true should skip cooldown check."""
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=1))

        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC?force=true")

        # Empty chain → 404 (not 429)
        assert resp.status_code == 404


class TestFetchUpsertsUnderlying:
    def test_creates_underlying_on_first_fetch(self, client, db):
        from tests.test_fetch import _make_chain

        chain = _make_chain()
        with patch("app.routers.fetch.DeribitClient") as MockClient, \
             patch("app.routers.fetch.get_risk_free_rate", new_callable=AsyncMock, return_value=0.05):
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=chain)
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 200
        row = db.query(Underlying).filter(Underlying.symbol == "BTC").first()
        assert row is not None
        assert row.market == "crypto"
        assert row.source == "deribit"
        assert row.last_spot == 75000.0
        assert row.last_snapshot_count == 5
        assert row.last_fetched_at is not None

    def test_updates_underlying_on_refetch(self, client, db):
        from tests.test_fetch import _make_chain

        # Pre-existing underlying with old data
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=10))
        db.commit()

        chain = _make_chain()
        with patch("app.routers.fetch.DeribitClient") as MockClient, \
             patch("app.routers.fetch.get_risk_free_rate", new_callable=AsyncMock, return_value=0.05):
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=chain)
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC")

        assert resp.status_code == 200
        rows = db.query(Underlying).filter(Underlying.symbol == "BTC").all()
        assert len(rows) == 1  # no duplicate
        assert rows[0].last_snapshot_count == 5
