"""Tests for API endpoints (alerts, contracts, surface, snapshots)."""
from __future__ import annotations

from datetime import date

from app.models import Alert, Contract, Snapshot


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAlertsEndpoint:
    def test_get_alerts_empty(self, client):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []
        assert data["next_cursor"] is None

    def test_get_alerts_with_data(self, client, sample_alert):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        alert = data["data"][0]
        assert alert["signal_type"] == "surface_outlier"
        assert alert["symbol"] == "BTC-27JUN26-100000-C"
        assert alert["strike"] == 100000.0
        assert alert["market_iv"] == 0.65
        assert alert["model_iv"] == 0.60
        assert alert["net_edge"] == 0.04

    def test_get_alerts_filter_by_signal_type(self, client, sample_alert):
        # Should find surface_outlier
        resp = client.get("/api/alerts?signal_type=surface_outlier")
        assert len(resp.json()["data"]) == 1

        # Should not find greek_divergence
        resp = client.get("/api/alerts?signal_type=greek_divergence")
        assert len(resp.json()["data"]) == 0

    def test_dismiss_alert(self, client, sample_alert):
        resp = client.post(f"/api/alerts/{sample_alert.id}/dismiss")
        assert resp.status_code == 200
        assert resp.json()["dismissed"] is True

        # Dismissed alert should not appear in list
        resp = client.get("/api/alerts")
        assert len(resp.json()["data"]) == 0

    def test_dismiss_nonexistent_alert(self, client):
        resp = client.post("/api/alerts/99999/dismiss")
        assert resp.status_code == 404

    def test_pagination(self, client, db, sample_contract):
        # Create multiple alerts
        for i in range(5):
            snap = Snapshot(
                contract_id=sample_contract.id,
                bid=100.0, ask=102.0, mid=101.0,
                market_iv=0.5, model_iv=0.45,
                net_edge=0.01 * (i + 1),
                triggered_by="user",
            )
            db.add(snap)
            db.flush()
            db.add(Alert(snapshot_id=snap.id, signal_type="surface_outlier"))
        db.flush()

        # Get first page (limit 2)
        resp = client.get("/api/alerts?limit=2")
        data = resp.json()
        assert len(data["data"]) == 2
        assert data["next_cursor"] is not None

        # Get next page
        cursor = data["next_cursor"]
        resp = client.get(f"/api/alerts?limit=2&cursor={cursor}")
        data = resp.json()
        assert len(data["data"]) == 2


class TestContractsEndpoint:
    def test_get_contracts_empty(self, client):
        resp = client.get("/api/contracts")
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert resp.json()["total"] == 0

    def test_get_contracts_with_data(self, client, sample_contract):
        resp = client.get("/api/contracts")
        data = resp.json()
        assert data["total"] == 1
        contract = data["data"][0]
        assert contract["symbol"] == "BTC-27JUN26-100000-C"
        assert contract["underlying"] == "BTC"
        assert contract["is_watchlisted"] is False

    def test_filter_by_underlying(self, client, db):
        db.add(Contract(symbol="BTC-TEST-C", underlying="BTC", market="crypto",
                        source="deribit", strike=100000, expiry=date(2026, 6, 27), option_type="C"))
        db.add(Contract(symbol="ETH-TEST-C", underlying="ETH", market="crypto",
                        source="deribit", strike=3000, expiry=date(2026, 6, 27), option_type="C"))
        db.flush()

        resp = client.get("/api/contracts?underlying=BTC")
        assert resp.json()["total"] == 1
        assert resp.json()["data"][0]["underlying"] == "BTC"

    def test_watch_contract(self, client, sample_contract):
        resp = client.post(f"/api/contracts/{sample_contract.id}/watch")
        assert resp.status_code == 200
        assert resp.json()["is_watchlisted"] is True

        # Verify it's watchlisted
        resp = client.get("/api/contracts?watchlisted=true")
        assert resp.json()["total"] == 1

    def test_unwatch_contract(self, client, db, sample_contract):
        sample_contract.is_watchlisted = True
        db.flush()

        resp = client.delete(f"/api/contracts/{sample_contract.id}/watch")
        assert resp.status_code == 200
        assert resp.json()["is_watchlisted"] is False

    def test_watch_nonexistent_contract(self, client):
        resp = client.post("/api/contracts/99999/watch")
        assert resp.status_code == 404


class TestSnapshotsEndpoint:
    def test_get_snapshots(self, client, sample_snapshot):
        resp = client.get(f"/api/snapshots/{sample_snapshot.contract_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["market_iv"] == 0.65
        assert data[0]["triggered_by"] == "user"

    def test_get_snapshots_empty(self, client, sample_contract):
        # Contract exists but no snapshots added
        resp = client.get(f"/api/snapshots/{sample_contract.id + 999}")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestSurfaceEndpoint:
    def test_get_surface_empty(self, client):
        resp = client.get("/api/surface/BTC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["points"] == []

    def test_get_surface_with_data(self, client, sample_snapshot):
        resp = client.get("/api/surface/BTC")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) == 1
        point = data["points"][0]
        assert point["symbol"] == "BTC-27JUN26-100000-C"
        assert point["market_iv"] == 0.65
        # Verify new fields are returned
        assert point["bid"] == 5000.0
        assert point["ask"] == 5200.0
        assert point["vega"] == 150.0
        assert point["delta_market"] == 0.45

    def test_get_alerts_filter_by_underlying(self, client, db):
        """Test filtering alerts by underlying."""
        contract = Contract(
            symbol="ETH-TEST-C", underlying="ETH", market="crypto",
            source="deribit", strike=3000, expiry=date(2026, 6, 27), option_type="C",
        )
        db.add(contract)
        db.flush()
        snap = Snapshot(
            contract_id=contract.id, bid=100, ask=102, mid=101,
            market_iv=0.5, model_iv=0.45, net_edge=5.0, triggered_by="user",
        )
        db.add(snap)
        db.flush()
        db.add(Alert(snapshot_id=snap.id, signal_type="surface_outlier"))
        db.flush()

        resp = client.get("/api/alerts?underlying=ETH")
        assert len(resp.json()["data"]) == 1
        assert resp.json()["data"][0]["underlying"] == "ETH"

        resp = client.get("/api/alerts?underlying=BTC")
        assert len(resp.json()["data"]) == 0

    def test_get_alerts_confidence_field(self, client, db, sample_contract):
        """Test that confidence is returned in alert responses."""
        snap = Snapshot(
            contract_id=sample_contract.id, bid=100, ask=102, mid=101,
            market_iv=0.5, model_iv=0.45, net_edge=50.0, triggered_by="user",
        )
        db.add(snap)
        db.flush()
        db.add(Alert(snapshot_id=snap.id, signal_type="surface_outlier", confidence="high"))
        db.flush()

        resp = client.get("/api/alerts")
        assert len(resp.json()["data"]) == 1
        assert resp.json()["data"][0]["confidence"] == "high"

    def test_snapshots_include_greeks(self, client, sample_snapshot):
        """Test that snapshot endpoint returns delta and vega."""
        resp = client.get(f"/api/snapshots/{sample_snapshot.contract_id}")
        data = resp.json()["data"][0]
        assert data["vega"] == 150.0
        assert data["delta_market"] == 0.45
        assert data["delta_model"] == 0.42
