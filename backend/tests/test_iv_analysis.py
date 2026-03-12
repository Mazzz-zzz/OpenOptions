"""Tests for the IV analysis endpoint."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models import Contract, Dividend, Earning, Snapshot, Underlying


def _make_pair(db, underlying, strike, expiry, call_iv=0.20, put_iv=0.21,
               call_mid=15.5, put_mid=14.5, model_iv_c=0.19, model_iv_p=0.20,
               deviation=-0.01, net_edge=0.50):
    """Create a matched call/put pair with snapshots."""
    c = Contract(
        symbol=f"{underlying}-{expiry}-C-{strike}", underlying=underlying,
        market="equity", source="tastytrade", strike=strike, expiry=expiry, option_type="C",
    )
    p = Contract(
        symbol=f"{underlying}-{expiry}-P-{strike}", underlying=underlying,
        market="equity", source="tastytrade", strike=strike, expiry=expiry, option_type="P",
    )
    db.add_all([c, p])
    db.flush()

    c_snap = Snapshot(
        contract_id=c.id, bid=call_mid - 0.5, ask=call_mid + 0.5, mid=call_mid,
        market_iv=call_iv, model_iv=model_iv_c, delta_market=0.52,
        vega=0.35, deviation=deviation, net_edge=net_edge, triggered_by="user",
    )
    p_snap = Snapshot(
        contract_id=p.id, bid=put_mid - 0.5, ask=put_mid + 0.5, mid=put_mid,
        market_iv=put_iv, model_iv=model_iv_p, delta_market=-0.48,
        vega=0.34, deviation=deviation, net_edge=net_edge * 0.8, triggered_by="user",
    )
    db.add_all([c_snap, p_snap])
    db.flush()
    return c, p, c_snap, p_snap


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
        assert data["forwards"] == []
        assert data["opportunities"] == []

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
        _make_pair(db, "SPY", 500.0, future_expiry)

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


class TestSyntheticForward:
    def test_forward_computed_from_put_call_pair(self, client, db):
        """Synthetic forward should be computed from put-call parity."""
        future_expiry = date.today() + timedelta(days=30)
        _make_pair(db, "SPY", 500.0, future_expiry, call_mid=15.5, put_mid=14.5)

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["forwards"]) == 1
        fwd = data["forwards"][0]
        assert fwd["expiry"] == future_expiry.isoformat()
        assert fwd["dte"] == 30
        # F = K + e^(rT) * (C - P) = 500 + e^(0.05*30/365) * (15.5 - 14.5) ≈ 501
        assert fwd["forward_price"] > 500.0
        assert fwd["forward_price"] < 510.0
        assert fwd["basis"] > 0  # forward > spot
        assert fwd["basis_pct"] is not None
        assert fwd["implied_yield"] is not None
        assert len(fwd["pairs"]) == 1
        pair = fwd["pairs"][0]
        assert pair["strike"] == 500.0
        assert pair["call_mid"] == 15.5
        assert pair["put_mid"] == 14.5
        assert pair["violation_pct"] >= 0

    def test_multiple_strikes_per_expiry(self, client, db):
        """Multiple put-call pairs at different strikes should all appear."""
        future_expiry = date.today() + timedelta(days=30)
        _make_pair(db, "SPY", 490.0, future_expiry, call_mid=20.0, put_mid=10.0)
        _make_pair(db, "SPY", 500.0, future_expiry, call_mid=15.5, put_mid=14.5)
        _make_pair(db, "SPY", 510.0, future_expiry, call_mid=10.0, put_mid=20.0)

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["forwards"]) == 1  # one expiry
        pairs = data["forwards"][0]["pairs"]
        assert len(pairs) == 3
        strikes = [p["strike"] for p in pairs]
        assert 490.0 in strikes
        assert 500.0 in strikes
        assert 510.0 in strikes

    def test_no_forward_without_matching_pair(self, client, db):
        """Expiry with only calls (no puts) should not produce a forward."""
        future_expiry = date.today() + timedelta(days=30)
        c = Contract(
            symbol="SPY-CALL-ONLY", underlying="SPY", market="equity",
            source="tastytrade", strike=500.0, expiry=future_expiry, option_type="C",
        )
        db.add(c)
        db.flush()
        db.add(Snapshot(
            contract_id=c.id, bid=15.0, ask=16.0, mid=15.5,
            market_iv=0.20, delta_market=0.52, vega=0.35, triggered_by="user",
        ))
        db.flush()

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["forwards"] == []


class TestRankedOpportunities:
    def test_opportunities_sorted_by_edge(self, client, db):
        """Opportunities should be sorted by net_edge descending."""
        future_expiry = date.today() + timedelta(days=30)
        _make_pair(db, "SPY", 500.0, future_expiry, net_edge=2.0, deviation=0.03)
        _make_pair(db, "SPY", 510.0, future_expiry, net_edge=5.0, deviation=0.05)

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()

        opps = data["opportunities"]
        assert len(opps) >= 2
        # Should be sorted descending by net_edge
        edges = [o["net_edge"] for o in opps]
        assert edges == sorted(edges, reverse=True)
        assert opps[0]["net_edge"] >= opps[-1]["net_edge"]

    def test_opportunities_exclude_negative_edge(self, client, db):
        """Contracts with net_edge <= 0 should not appear in opportunities."""
        future_expiry = date.today() + timedelta(days=30)
        _make_pair(db, "SPY", 500.0, future_expiry, net_edge=-1.0, deviation=0.01)

        resp = client.get("/api/iv-analysis/SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["opportunities"] == []

    def test_opportunities_include_contract_details(self, client, db):
        """Each opportunity should include strike, expiry, option_type, etc."""
        future_expiry = date.today() + timedelta(days=30)
        _make_pair(db, "SPY", 500.0, future_expiry, net_edge=3.0, deviation=0.04)

        resp = client.get("/api/iv-analysis/SPY")
        data = resp.json()
        opps = data["opportunities"]
        assert len(opps) >= 1

        opp = opps[0]
        assert "strike" in opp
        assert "expiry" in opp
        assert "option_type" in opp
        assert "deviation" in opp
        assert "net_edge" in opp
        assert "vega" in opp
        assert "delta" in opp
        assert opp["strike"] == 500.0
