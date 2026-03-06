"""Tests for the underlyings endpoints."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Dividend, Earning, Underlying
from app.services.deribit import OptionQuote


def _make_underlying(db, symbol="BTC", last_fetched_at=None, **kwargs):
    u = Underlying(
        symbol=symbol,
        market="crypto" if symbol in ("BTC", "ETH") else "equity",
        source="deribit" if symbol in ("BTC", "ETH") else "tastytrade",
        last_fetched_at=last_fetched_at,
        last_spot=75000.0 if symbol == "BTC" else 100.0,
        last_snapshot_count=5,
        last_alert_count=1,
        **kwargs,
    )
    db.add(u)
    db.flush()
    return u


class TestListUnderlyings:
    def test_list_empty(self, client):
        resp = client.get("/api/underlyings")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_returns_underlyings(self, client, db):
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=10))
        _make_underlying(db, "SPY", datetime.now(timezone.utc) - timedelta(minutes=3))
        resp = client.get("/api/underlyings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        # SPY fetched more recently, should be first
        assert data[0]["symbol"] == "SPY"
        assert data[1]["symbol"] == "BTC"


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

        # Empty chain -> 404 (not 429)
        assert resp.status_code == 404

    def test_force_bypasses_cooldown(self, client, db):
        """force=true should skip cooldown check."""
        _make_underlying(db, "BTC", datetime.now(timezone.utc) - timedelta(minutes=1))

        with patch("app.routers.fetch.DeribitClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_chain = AsyncMock(return_value=[])
            instance.close = AsyncMock()

            resp = client.post("/api/fetch/BTC?force=true")

        # Empty chain -> 404 (not 429)
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


class TestUnderlyingsReturnMetrics:
    def test_list_returns_market_metrics(self, client, db):
        """Underlyings endpoint returns iv_rank, iv_percentile, liquidity_rating."""
        _make_underlying(
            db, "SPY",
            datetime.now(timezone.utc) - timedelta(minutes=5),
            iv_rank=32.5, iv_percentile=28.0, liquidity_rating=4,
        )
        resp = client.get("/api/underlyings")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["iv_rank"] == 32.5
        assert data[0]["iv_percentile"] == 28.0
        assert data[0]["liquidity_rating"] == 4

    def test_list_returns_null_metrics_when_unset(self, client, db):
        """Metrics default to null for crypto/unfetched symbols."""
        _make_underlying(db, "BTC", datetime.now(timezone.utc))
        resp = client.get("/api/underlyings")
        data = resp.json()["data"][0]
        assert data["iv_rank"] is None
        assert data["iv_percentile"] is None
        assert data["liquidity_rating"] is None


class TestEarningsDividendsModels:
    def test_earnings_stored_and_queryable(self, db):
        u = _make_underlying(db, "AAPL", datetime.now(timezone.utc))
        db.add(Earning(underlying_id=u.id, occurred_date=date(2026, 1, 15), eps=2.35))
        db.add(Earning(underlying_id=u.id, occurred_date=date(2025, 10, 15), eps=-0.10))
        db.flush()
        earnings = db.query(Earning).filter(Earning.underlying_id == u.id).all()
        assert len(earnings) == 2

    def test_dividends_stored_and_queryable(self, db):
        u = _make_underlying(db, "AAPL", datetime.now(timezone.utc))
        db.add(Dividend(underlying_id=u.id, occurred_date=date(2026, 2, 10), amount=0.24))
        db.flush()
        dividends = db.query(Dividend).filter(Dividend.underlying_id == u.id).all()
        assert len(dividends) == 1
        assert float(dividends[0].amount) == 0.24

    def test_earnings_unique_constraint(self, db):
        """Duplicate date for same underlying should fail."""
        u = _make_underlying(db, "AAPL", datetime.now(timezone.utc))
        db.add(Earning(underlying_id=u.id, occurred_date=date(2026, 1, 15), eps=2.35))
        db.flush()
        db.add(Earning(underlying_id=u.id, occurred_date=date(2026, 1, 15), eps=2.40))
        import sqlalchemy
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            db.flush()
