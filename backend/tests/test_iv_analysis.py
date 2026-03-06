"""Tests for the IV analysis endpoint."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models import Contract, Dividend, Earning, Snapshot, Underlying


class TestIvAnalysisEndpoint:
    def test_empty_returns_structure(self, client):
        resp = client.get("/api/iv-analysis/BTC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["term_structure"] == []
        assert data["spot"] is None
        assert data["market_metrics"] is None
        assert data["earnings"] == []
        assert data["dividends"] == []
        assert data["ts_slope"] is None

    def test_returns_market_metrics(self, client, db):
        """When underlying has market metrics, they appear in response."""
        u = Underlying(
            symbol="SPY", market="equity", source="tastytrade",
            last_fetched_at=datetime.now(timezone.utc),
            last_spot=500.0, last_snapshot_count=10, last_alert_count=0,
            iv_index=0.1842, iv_rank=32.5, iv_percentile=28.0,
            liquidity_rating=4,
        )
        db.add(u)
        db.flush()

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()
        mm = data["market_metrics"]
        assert mm is not None
        assert abs(mm["iv_index"] - 0.1842) < 1e-4
        assert abs(mm["iv_rank"] - 32.5) < 0.1
        assert mm["liquidity_rating"] == 4

    def test_returns_earnings_and_dividends(self, client, db):
        u = Underlying(
            symbol="AAPL", market="equity", source="tastytrade",
            last_fetched_at=datetime.now(timezone.utc),
            last_spot=200.0, last_snapshot_count=10, last_alert_count=0,
        )
        db.add(u)
        db.flush()

        db.add(Earning(underlying_id=u.id, occurred_date=date(2026, 1, 15), eps=2.35))
        db.add(Earning(underlying_id=u.id, occurred_date=date(2025, 10, 15), eps=1.90))
        db.add(Dividend(underlying_id=u.id, occurred_date=date(2026, 2, 10), amount=0.24))
        db.flush()

        resp = client.get("/api/iv-analysis/AAPL")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["earnings"]) == 2
        # Sorted desc by date
        assert data["earnings"][0]["date"] == "2026-01-15"
        assert abs(data["earnings"][0]["eps"] - 2.35) < 0.01
        assert len(data["dividends"]) == 1
        assert abs(data["dividends"][0]["amount"] - 0.24) < 0.001

    def test_with_snapshot_data(self, client, db):
        """Full test with contracts + snapshots to verify term structure works."""
        future_expiry = date.today() + timedelta(days=30)
        c1 = Contract(
            symbol="SPY-TEST-C-500", underlying="SPY", market="equity",
            source="tastytrade", strike=500.0, expiry=future_expiry, option_type="C",
        )
        c2 = Contract(
            symbol="SPY-TEST-P-500", underlying="SPY", market="equity",
            source="tastytrade", strike=500.0, expiry=future_expiry, option_type="P",
        )
        db.add_all([c1, c2])
        db.flush()

        db.add(Snapshot(
            contract_id=c1.id, bid=15.0, ask=16.0, mid=15.5,
            market_iv=0.20, model_iv=0.19, delta_market=0.52,
            vega=0.35, deviation=-0.01, net_edge=0.50, triggered_by="user",
        ))
        db.add(Snapshot(
            contract_id=c2.id, bid=14.0, ask=15.0, mid=14.5,
            market_iv=0.21, model_iv=0.20, delta_market=-0.48,
            vega=0.34, deviation=-0.01, net_edge=0.40, triggered_by="user",
        ))
        db.flush()

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()

        assert data["spot"] is not None
        assert len(data["term_structure"]) == 1
        ts = data["term_structure"][0]
        assert ts["expiry"] == future_expiry.isoformat()
        assert ts["atm_iv"] > 0
        assert "market_metrics" in data
        assert "earnings" in data
        assert "dividends" in data
