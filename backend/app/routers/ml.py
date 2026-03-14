"""ML / Numerai experiment tracking & model registry endpoints."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    MlEnsemble,
    MlEpochMetric,
    MlExperiment,
    MlModel,
    MlRound,
    MlRun,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic schemas ─────────────────────────────────────────────────


class ExperimentOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    created_at: str
    run_count: int = 0
    best_corr: Optional[float] = None

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: int
    experiment_id: int
    model_type: str
    status: str
    hyperparams_json: Optional[str] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None
    feature_exposure: Optional[float] = None
    max_drawdown: Optional[float] = None
    mmc: Optional[float] = None
    progress_pct: Optional[float] = None
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    instance_type: Optional[str] = None
    cost_usd: Optional[float] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class EpochMetricOut(BaseModel):
    epoch: int
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None

    class Config:
        from_attributes = True


class ModelOut(BaseModel):
    id: int
    name: str
    model_type: str
    stage: str
    version: int
    run_id: Optional[int] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None
    feature_exposure: Optional[float] = None
    max_drawdown: Optional[float] = None
    mmc: Optional[float] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ModelCreate(BaseModel):
    name: str
    model_type: str
    run_id: Optional[int] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None


class ModelPatch(BaseModel):
    stage: Optional[str] = None


class TrainRequest(BaseModel):
    experiment_name: str
    description: Optional[str] = None
    feature_set: str = "medium"
    model_type: str = "lgbm"
    instance_type: str = "ml.m5.xlarge"
    hyperparams: Optional[dict] = None
    upload: bool = False
    # NEW: Model configuration options
    neutralization_pct: float = 50.0  # 0-100


class ExperimentCreate(BaseModel):
    name: str
    description: Optional[str] = None


class RunPatch(BaseModel):
    status: Optional[str] = None
    progress_pct: Optional[float] = None
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None
    feature_exposure: Optional[float] = None
    max_drawdown: Optional[float] = None
    mmc: Optional[float] = None
    instance_type: Optional[str] = None
    cost_usd: Optional[float] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class EpochMetricIn(BaseModel):
    epoch: int
    train_loss: Optional[float] = None
    val_loss: Optional[float] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None


class MetricsBatch(BaseModel):
    metrics: List[EpochMetricIn]


class RoundOut(BaseModel):
    id: int
    round_number: int
    model_name: str
    live_corr: Optional[float] = None
    resolved_corr: Optional[float] = None
    payout_nmr: Optional[float] = None
    status: str
    submitted_at: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class EnsembleOut(BaseModel):
    id: int
    method: str
    config_json: Optional[str] = None
    correlation: Optional[float] = None
    sharpe: Optional[float] = None
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


# ── Helpers ──────────────────────────────────────────────────────────


def _ts(dt) -> str:
    if dt is None:
        return ""
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def _fl(v) -> Optional[float]:
    return float(v) if v is not None else None


def _check_poller_key(x_poller_key: Optional[str] = Header(None)):
    """Verify poller API key for internal endpoints."""
    settings = get_settings()
    if not settings.ml_poller_api_key:
        return  # no key configured = allow all (dev mode)
    if x_poller_key != settings.ml_poller_api_key:
        raise HTTPException(status_code=403, detail="Invalid poller key")


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/ml/overview")
async def ml_overview(db: Session = Depends(get_db)):
    """Summary: active runs, best model, latest round, ensemble score."""
    active_runs = db.query(sa_func.count(MlRun.id)).filter(
        MlRun.status.in_(["pending", "running"])
    ).scalar() or 0

    best_model = (
        db.query(MlModel)
        .filter(MlModel.stage == "prod")
        .order_by(MlModel.correlation.desc().nullslast())
        .first()
    )

    latest_round = (
        db.query(MlRound)
        .order_by(MlRound.round_number.desc())
        .first()
    )

    active_ensemble = (
        db.query(MlEnsemble)
        .filter(MlEnsemble.is_active == True)
        .first()
    )

    # Recent runs
    recent = (
        db.query(MlRun)
        .order_by(MlRun.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "active_runs": active_runs,
        "best_model": {
            "name": best_model.name,
            "correlation": _fl(best_model.correlation),
            "sharpe": _fl(best_model.sharpe),
            "feature_exposure": _fl(best_model.feature_exposure),
            "max_drawdown": _fl(best_model.max_drawdown),
            "mmc": _fl(best_model.mmc),
        } if best_model else None,
        "latest_round": {
            "round_number": latest_round.round_number,
            "status": latest_round.status,
            "live_corr": _fl(latest_round.live_corr),
        } if latest_round else None,
        "ensemble_score": _fl(active_ensemble.correlation) if active_ensemble else None,
        "total_cost_usd": sum(float(r.cost_usd) for r in recent if r.cost_usd is not None),
        "recent_runs": [
            {
                "id": r.id,
                "model_type": r.model_type,
                "status": r.status,
                "correlation": _fl(r.correlation),
                "sharpe": _fl(r.sharpe),
                "feature_exposure": _fl(r.feature_exposure),
                "max_drawdown": _fl(r.max_drawdown),
                "mmc": _fl(r.mmc),
                "instance_type": r.instance_type,
                "cost_usd": _fl(r.cost_usd),
                "started_at": _ts(r.started_at),
                "finished_at": _ts(r.finished_at),
            }
            for r in recent
        ],
    }


@router.get("/ml/experiments")
async def list_experiments(
    cursor: Optional[int] = None,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    """Cursor-based paginated experiment list."""
    query = db.query(MlExperiment)

    if cursor is not None:
        query = query.filter(MlExperiment.id < cursor)

    query = query.order_by(MlExperiment.id.desc()).limit(limit + 1)
    experiments = query.all()

    has_more = len(experiments) > limit
    experiments = experiments[:limit]

    data = []
    for exp in experiments:
        run_count = db.query(sa_func.count(MlRun.id)).filter(
            MlRun.experiment_id == exp.id
        ).scalar() or 0
        best_corr = db.query(sa_func.max(MlRun.correlation)).filter(
            MlRun.experiment_id == exp.id
        ).scalar()
        data.append(ExperimentOut(
            id=exp.id,
            name=exp.name,
            description=exp.description,
            status=exp.status,
            created_at=_ts(exp.created_at),
            run_count=run_count,
            best_corr=_fl(best_corr),
        ))

    return {
        "data": data,
        "next_cursor": experiments[-1].id if has_more and experiments else None,
    }


@router.get("/ml/experiments/{experiment_id}/runs")
async def list_runs(experiment_id: int, db: Session = Depends(get_db)):
    """Runs for an experiment, with hyperparams + metrics."""
    exp = db.query(MlExperiment).filter(MlExperiment.id == experiment_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    runs = (
        db.query(MlRun)
        .filter(MlRun.experiment_id == experiment_id)
        .order_by(MlRun.created_at.desc())
        .all()
    )

    return {
        "data": [
            RunOut(
                id=r.id,
                experiment_id=r.experiment_id,
                model_type=r.model_type,
                status=r.status,
                hyperparams_json=r.hyperparams_json,
                correlation=_fl(r.correlation),
                sharpe=_fl(r.sharpe),
                feature_exposure=_fl(r.feature_exposure),
                max_drawdown=_fl(r.max_drawdown),
                mmc=_fl(r.mmc),
                progress_pct=_fl(r.progress_pct),
                current_epoch=r.current_epoch,
                total_epochs=r.total_epochs,
                instance_type=r.instance_type,
                cost_usd=_fl(r.cost_usd),
                started_at=_ts(r.started_at),
                finished_at=_ts(r.finished_at),
                created_at=_ts(r.created_at),
            )
            for r in runs
        ]
    }


@router.get("/ml/runs/{run_id}/metrics")
async def run_metrics(run_id: int, db: Session = Depends(get_db)):
    """Epoch-level time-series for loss curves."""
    run = db.query(MlRun).filter(MlRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    metrics = (
        db.query(MlEpochMetric)
        .filter(MlEpochMetric.run_id == run_id)
        .order_by(MlEpochMetric.epoch)
        .all()
    )

    return {
        "data": [
            EpochMetricOut(
                epoch=m.epoch,
                train_loss=_fl(m.train_loss),
                val_loss=_fl(m.val_loss),
                correlation=_fl(m.correlation),
                sharpe=_fl(m.sharpe),
            )
            for m in metrics
        ]
    }


@router.get("/ml/models")
async def list_models(db: Session = Depends(get_db)):
    """Registered models with stage/version."""
    models = (
        db.query(MlModel)
        .order_by(MlModel.updated_at.desc())
        .all()
    )
    return {
        "data": [
            ModelOut(
                id=m.id,
                name=m.name,
                model_type=m.model_type,
                stage=m.stage,
                version=m.version,
                run_id=m.run_id,
                correlation=_fl(m.correlation),
                sharpe=_fl(m.sharpe),
                feature_exposure=_fl(m.feature_exposure),
                max_drawdown=_fl(m.max_drawdown),
                mmc=_fl(m.mmc),
                created_at=_ts(m.created_at),
                updated_at=_ts(m.updated_at),
            )
            for m in models
        ]
    }


@router.post("/ml/models")
async def create_model(body: ModelCreate, db: Session = Depends(get_db)):
    """Register a new model (promote from run)."""
    existing = db.query(MlModel).filter(MlModel.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Model name already exists")

    if body.run_id:
        run = db.query(MlRun).filter(MlRun.id == body.run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

    model = MlModel(
        name=body.name,
        model_type=body.model_type,
        run_id=body.run_id,
        correlation=body.correlation,
        sharpe=body.sharpe,
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    return ModelOut(
        id=model.id,
        name=model.name,
        model_type=model.model_type,
        stage=model.stage,
        version=model.version,
        run_id=model.run_id,
        correlation=_fl(model.correlation),
        sharpe=_fl(model.sharpe),
        created_at=_ts(model.created_at),
        updated_at=_ts(model.updated_at),
    )


@router.patch("/ml/models/{model_id}")
async def update_model(model_id: int, body: ModelPatch, db: Session = Depends(get_db)):
    """Update model stage (dev -> staging -> prod)."""
    model = db.query(MlModel).filter(MlModel.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    valid_stages = {"dev", "staging", "prod"}
    if body.stage is not None:
        if body.stage not in valid_stages:
            raise HTTPException(status_code=400, detail=f"Stage must be one of {valid_stages}")
        model.stage = body.stage

    db.commit()
    db.refresh(model)

    return ModelOut(
        id=model.id,
        name=model.name,
        model_type=model.model_type,
        stage=model.stage,
        version=model.version,
        run_id=model.run_id,
        correlation=_fl(model.correlation),
        sharpe=_fl(model.sharpe),
        created_at=_ts(model.created_at),
        updated_at=_ts(model.updated_at),
    )


@router.get("/ml/rounds")
async def list_rounds(
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Numerai round history."""
    rounds = (
        db.query(MlRound)
        .order_by(MlRound.round_number.desc())
        .limit(limit)
        .all()
    )
    return {
        "data": [
            RoundOut(
                id=r.id,
                round_number=r.round_number,
                model_name=r.model_name,
                live_corr=_fl(r.live_corr),
                resolved_corr=_fl(r.resolved_corr),
                payout_nmr=_fl(r.payout_nmr),
                status=r.status,
                submitted_at=_ts(r.submitted_at),
                created_at=_ts(r.created_at),
            )
            for r in rounds
        ]
    }


@router.get("/ml/ensemble")
async def get_ensemble(db: Session = Depends(get_db)):
    """Current ensemble config + performance."""
    ensemble = (
        db.query(MlEnsemble)
        .filter(MlEnsemble.is_active == True)
        .first()
    )
    if not ensemble:
        return {"data": None}

    return {
        "data": EnsembleOut(
            id=ensemble.id,
            method=ensemble.method,
            config_json=ensemble.config_json,
            correlation=_fl(ensemble.correlation),
            sharpe=_fl(ensemble.sharpe),
            is_active=ensemble.is_active,
            created_at=_ts(ensemble.created_at),
        )
    }


# ── Write endpoints ─────────────────────────────────────────────────


@router.post("/ml/train")
async def trigger_training(body: TrainRequest, db: Session = Depends(get_db)):
    """Create experiment + run and start a SageMaker training job."""
    from app.services.sagemaker_service import create_training_job

    # Validate inputs
    valid_feature_sets = {"small", "medium", "all"}
    if body.feature_set not in valid_feature_sets:
        raise HTTPException(status_code=400, detail=f"feature_set must be one of {valid_feature_sets}")

    valid_model_types = {"lgbm", "catboost"}
    if body.model_type not in valid_model_types:
        raise HTTPException(status_code=400, detail=f"model_type must be one of {valid_model_types}")

    settings = get_settings()
    if not settings.sagemaker_role_arn or not settings.sagemaker_ecr_image:
        raise HTTPException(status_code=503, detail="SageMaker not configured")

    # Find or create experiment
    exp = db.query(MlExperiment).filter(MlExperiment.name == body.experiment_name).first()
    if not exp:
        exp = MlExperiment(name=body.experiment_name, description=body.description)
        db.add(exp)
        db.flush()

    # Create run
    hyperparams = body.hyperparams or {}
    run = MlRun(
        experiment_id=exp.id,
        model_type=body.model_type,
        status="pending",
        hyperparams_json=json.dumps(hyperparams) if hyperparams else None,
        instance_type=body.instance_type,
    )
    db.add(run)
    db.flush()

    # Build job name: oo-{experiment}-{run_id}-{timestamp}
    safe_name = re.sub(r"[^a-zA-Z0-9-]", "-", body.experiment_name)[:40]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_name = f"oo-{safe_name}-{run.id}-{ts}"

    try:
        job_arn = create_training_job(
            job_name=job_name,
            hyperparams=hyperparams,
            instance_type=body.instance_type,
            feature_set=body.feature_set,
            upload=body.upload,
            model_type=body.model_type,
            neutralization_pct=body.neutralization_pct,
        )
        run.sagemaker_job_name = job_name
        run.sagemaker_job_arn = job_arn
        run.status = "pending"
        db.commit()
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)[:2000]
        db.commit()
        logger.exception("Failed to create SageMaker job")
        raise HTTPException(status_code=500, detail=f"Failed to start training: {e}")

    return {
        "run_id": run.id,
        "experiment_id": exp.id,
        "sagemaker_job_name": job_name,
    }


@router.post("/ml/experiments")
async def create_experiment(body: ExperimentCreate, db: Session = Depends(get_db)):
    """Create a new experiment."""
    existing = db.query(MlExperiment).filter(MlExperiment.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Experiment name already exists")

    exp = MlExperiment(name=body.name, description=body.description)
    db.add(exp)
    db.commit()
    db.refresh(exp)

    return ExperimentOut(
        id=exp.id,
        name=exp.name,
        description=exp.description,
        status=exp.status,
        created_at=_ts(exp.created_at),
        run_count=0,
        best_corr=None,
    )


@router.patch("/ml/runs/{run_id}")
async def update_run(
    run_id: int,
    body: RunPatch,
    db: Session = Depends(get_db),
    _auth: None = Depends(_check_poller_key),
):
    """Update run progress/status/metrics (called by poller Lambda)."""
    run = db.query(MlRun).filter(MlRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    valid_statuses = {"pending", "running", "completed", "failed"}

    if body.status is not None:
        if body.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")
        run.status = body.status
    if body.progress_pct is not None:
        run.progress_pct = body.progress_pct
    if body.current_epoch is not None:
        run.current_epoch = body.current_epoch
    if body.total_epochs is not None:
        run.total_epochs = body.total_epochs
    if body.correlation is not None:
        run.correlation = body.correlation
    if body.sharpe is not None:
        run.sharpe = body.sharpe
    if body.feature_exposure is not None:
        run.feature_exposure = body.feature_exposure
    if body.max_drawdown is not None:
        run.max_drawdown = body.max_drawdown
    if body.mmc is not None:
        run.mmc = body.mmc
    if body.instance_type is not None:
        run.instance_type = body.instance_type
    if body.cost_usd is not None:
        run.cost_usd = body.cost_usd
    if body.error_message is not None:
        run.error_message = body.error_message[:2000]
    if body.started_at is not None:
        run.started_at = body.started_at
    if body.finished_at is not None:
        run.finished_at = body.finished_at

    db.commit()
    db.refresh(run)

    return RunOut(
        id=run.id,
        experiment_id=run.experiment_id,
        model_type=run.model_type,
        status=run.status,
        hyperparams_json=run.hyperparams_json,
        correlation=_fl(run.correlation),
        sharpe=_fl(run.sharpe),
        feature_exposure=_fl(run.feature_exposure),
        max_drawdown=_fl(run.max_drawdown),
        progress_pct=_fl(run.progress_pct),
        current_epoch=run.current_epoch,
        total_epochs=run.total_epochs,
        instance_type=run.instance_type,
        cost_usd=_fl(run.cost_usd),
        started_at=_ts(run.started_at),
        finished_at=_ts(run.finished_at),
        created_at=_ts(run.created_at),
    )


@router.post("/ml/runs/{run_id}/metrics")
async def batch_insert_metrics(
    run_id: int,
    body: MetricsBatch,
    db: Session = Depends(get_db),
    _auth: None = Depends(_check_poller_key),
):
    """Batch-insert epoch metrics (called by poller Lambda)."""
    run = db.query(MlRun).filter(MlRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    inserted = 0
    for m in body.metrics:
        # Skip if epoch already exists
        existing = db.query(MlEpochMetric).filter(
            MlEpochMetric.run_id == run_id,
            MlEpochMetric.epoch == m.epoch,
        ).first()
        if existing:
            continue

        metric = MlEpochMetric(
            run_id=run_id,
            epoch=m.epoch,
            train_loss=m.train_loss,
            val_loss=m.val_loss,
            correlation=m.correlation,
            sharpe=m.sharpe,
        )
        db.add(metric)
        inserted += 1

    db.commit()
    return {"inserted": inserted}


@router.post("/ml/runs/{run_id}/cancel")
async def cancel_run(run_id: int, db: Session = Depends(get_db)):
    """Cancel a running training job."""
    run = db.query(MlRun).filter(MlRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Run is not active")

    if run.sagemaker_job_name:
        from app.services.sagemaker_service import stop_job
        stop_job(run.sagemaker_job_name)

    run.status = "failed"
    run.error_message = "Cancelled by user"
    run.finished_at = datetime.now(timezone.utc)
    db.commit()

    return {"run_id": run.id, "status": "failed"}
