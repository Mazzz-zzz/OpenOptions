"""Tests for ML / Numerai endpoints."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.models import MlEnsemble, MlEpochMetric, MlExperiment, MlModel, MlRound, MlRun


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def experiment(db: Session) -> MlExperiment:
    exp = MlExperiment(name="lgbm-baseline", description="First LightGBM run")
    db.add(exp)
    db.flush()
    return exp


@pytest.fixture
def run(db: Session, experiment: MlExperiment) -> MlRun:
    r = MlRun(
        experiment_id=experiment.id,
        model_type="lgbm",
        status="completed",
        hyperparams_json='{"num_leaves": 31, "learning_rate": 0.05}',
        correlation=0.025,
        sharpe=1.2,
        feature_exposure=0.01,
        max_drawdown=-0.03,
        current_epoch=100,
        total_epochs=100,
        started_at=datetime(2026, 3, 1, 10, 0),
        finished_at=datetime(2026, 3, 1, 12, 0),
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def epoch_metrics(db: Session, run: MlRun) -> list[MlEpochMetric]:
    metrics = []
    for i in range(5):
        m = MlEpochMetric(
            run_id=run.id,
            epoch=i + 1,
            train_loss=0.5 - i * 0.05,
            val_loss=0.55 - i * 0.04,
            correlation=0.01 + i * 0.005,
            sharpe=0.5 + i * 0.2,
        )
        db.add(m)
        metrics.append(m)
    db.flush()
    return metrics


@pytest.fixture
def model(db: Session, run: MlRun) -> MlModel:
    m = MlModel(
        name="lgbm-v1",
        model_type="lgbm",
        stage="dev",
        version=1,
        run_id=run.id,
        correlation=0.025,
        sharpe=1.2,
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def prod_model(db: Session, run: MlRun) -> MlModel:
    m = MlModel(
        name="lgbm-prod",
        model_type="lgbm",
        stage="prod",
        version=2,
        run_id=run.id,
        correlation=0.03,
        sharpe=1.5,
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def ml_round(db: Session) -> MlRound:
    r = MlRound(
        round_number=500,
        model_name="lgbm-prod",
        live_corr=0.022,
        status="pending",
        submitted_at=datetime(2026, 3, 10),
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def ensemble(db: Session) -> MlEnsemble:
    e = MlEnsemble(
        method="rank_average",
        config_json='{"models": ["lgbm-v1", "lgbm-v2"]}',
        correlation=0.028,
        sharpe=1.4,
        is_active=True,
    )
    db.add(e)
    db.flush()
    return e


# ── Overview ─────────────────────────────────────────────────────────


class TestOverview:
    def test_overview_empty(self, client):
        res = client.get("/api/ml/overview")
        assert res.status_code == 200
        body = res.json()
        assert body["active_runs"] == 0
        assert body["best_model"] is None
        assert body["latest_round"] is None
        assert body["ensemble_score"] is None

    def test_overview_with_data(self, client, run, prod_model, ml_round, ensemble):
        res = client.get("/api/ml/overview")
        assert res.status_code == 200
        body = res.json()
        assert body["active_runs"] == 0  # run is completed
        assert body["best_model"]["name"] == "lgbm-prod"
        assert body["best_model"]["correlation"] == 0.03
        assert body["latest_round"]["round_number"] == 500
        assert body["ensemble_score"] == 0.028
        assert len(body["recent_runs"]) == 1


# ── Experiments ──────────────────────────────────────────────────────


class TestExperiments:
    def test_list_empty(self, client):
        res = client.get("/api/ml/experiments")
        assert res.status_code == 200
        assert res.json()["data"] == []
        assert res.json()["next_cursor"] is None

    def test_list_with_data(self, client, experiment, run):
        res = client.get("/api/ml/experiments")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "lgbm-baseline"
        assert data[0]["run_count"] == 1
        assert data[0]["best_corr"] == 0.025

    def test_cursor_pagination(self, client, db):
        # Create multiple experiments
        for i in range(5):
            db.add(MlExperiment(name=f"exp-{i}"))
        db.flush()

        res1 = client.get("/api/ml/experiments?limit=3")
        assert res1.status_code == 200
        body1 = res1.json()
        assert len(body1["data"]) == 3
        assert body1["next_cursor"] is not None

        res2 = client.get(f"/api/ml/experiments?limit=3&cursor={body1['next_cursor']}")
        body2 = res2.json()
        assert len(body2["data"]) == 2
        assert body2["next_cursor"] is None


# ── Runs ─────────────────────────────────────────────────────────────


class TestRuns:
    def test_list_runs(self, client, experiment, run):
        res = client.get(f"/api/ml/experiments/{experiment.id}/runs")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 1
        assert data[0]["model_type"] == "lgbm"
        assert data[0]["correlation"] == 0.025

    def test_runs_404(self, client):
        res = client.get("/api/ml/experiments/999/runs")
        assert res.status_code == 404


# ── Epoch Metrics ────────────────────────────────────────────────────


class TestEpochMetrics:
    def test_get_metrics(self, client, run, epoch_metrics):
        res = client.get(f"/api/ml/runs/{run.id}/metrics")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 5
        assert data[0]["epoch"] == 1
        assert data[4]["epoch"] == 5

    def test_metrics_404(self, client):
        res = client.get("/api/ml/runs/999/metrics")
        assert res.status_code == 404


# ── Models ───────────────────────────────────────────────────────────


class TestModels:
    def test_list_models(self, client, model):
        res = client.get("/api/ml/models")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "lgbm-v1"
        assert data[0]["stage"] == "dev"

    def test_create_model(self, client, run):
        res = client.post("/api/ml/models", json={
            "name": "new-model",
            "model_type": "lgbm",
            "run_id": run.id,
            "correlation": 0.03,
            "sharpe": 1.5,
        })
        assert res.status_code == 200
        body = res.json()
        assert body["name"] == "new-model"
        assert body["stage"] == "dev"

    def test_create_duplicate_name(self, client, model):
        res = client.post("/api/ml/models", json={
            "name": "lgbm-v1",
            "model_type": "lgbm",
        })
        assert res.status_code == 409

    def test_create_model_invalid_run(self, client):
        res = client.post("/api/ml/models", json={
            "name": "bad-model",
            "model_type": "lgbm",
            "run_id": 999,
        })
        assert res.status_code == 404

    def test_promote_stage(self, client, model):
        res = client.patch(f"/api/ml/models/{model.id}", json={"stage": "staging"})
        assert res.status_code == 200
        assert res.json()["stage"] == "staging"

        res2 = client.patch(f"/api/ml/models/{model.id}", json={"stage": "prod"})
        assert res2.status_code == 200
        assert res2.json()["stage"] == "prod"

    def test_invalid_stage(self, client, model):
        res = client.patch(f"/api/ml/models/{model.id}", json={"stage": "invalid"})
        assert res.status_code == 400

    def test_patch_404(self, client):
        res = client.patch("/api/ml/models/999", json={"stage": "prod"})
        assert res.status_code == 404


# ── Rounds ───────────────────────────────────────────────────────────


class TestRounds:
    def test_list_rounds(self, client, ml_round):
        res = client.get("/api/ml/rounds")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 1
        assert data[0]["round_number"] == 500
        assert data[0]["live_corr"] == 0.022


# ── Ensemble ─────────────────────────────────────────────────────────


class TestEnsemble:
    def test_no_active_ensemble(self, client):
        res = client.get("/api/ml/ensemble")
        assert res.status_code == 200
        assert res.json()["data"] is None

    def test_active_ensemble(self, client, ensemble):
        res = client.get("/api/ml/ensemble")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["method"] == "rank_average"
        assert data["correlation"] == 0.028
        assert data["is_active"] is True
