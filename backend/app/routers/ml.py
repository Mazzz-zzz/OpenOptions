"""ML / Numerai experiment tracking & model registry endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    MlEnsemble,
    MlEpochMetric,
    MlExperiment,
    MlModel,
    MlRound,
    MlRun,
)

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
    progress_pct: Optional[float] = None
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
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
        } if best_model else None,
        "latest_round": {
            "round_number": latest_round.round_number,
            "status": latest_round.status,
            "live_corr": _fl(latest_round.live_corr),
        } if latest_round else None,
        "ensemble_score": _fl(active_ensemble.correlation) if active_ensemble else None,
        "recent_runs": [
            {
                "id": r.id,
                "model_type": r.model_type,
                "status": r.status,
                "correlation": _fl(r.correlation),
                "sharpe": _fl(r.sharpe),
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
                progress_pct=_fl(r.progress_pct),
                current_epoch=r.current_epoch,
                total_epochs=r.total_epochs,
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
