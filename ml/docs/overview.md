# Architecture Overview

## System Architecture

The ML pipeline has two execution modes: **local CLI** and **SageMaker cloud training**. Both run the same `training.trainer.run_training()` code — the only difference is where it executes and how progress is reported.

```
                         ┌──────────────────────────────────────┐
                         │           Local CLI Mode             │
                         │                                      │
                         │  python3 -m training.trainer         │
                         │     --feature-set small              │
                         │     --output ./output                │
                         │                                      │
                         │  Writes: output/model_*, metrics.json│
                         │  Needs: ~16GB RAM (small set)        │
                         └──────────────────────────────────────┘

                         ┌──────────────────────────────────────┐
                         │         SageMaker Cloud Mode         │
┌──────────┐  POST       │                                      │
│Dashboard │──/ml/train──┤  API Lambda (FastAPI)                │
│ /ml tab  │             │    │                                 │
│          │  polls 5s   │    │ boto3.create_training_job()     │
│  ◄───────┤──/ml/overview    ▼                                 │
│          │             │  SageMaker Training Job              │
│  Loss    │             │  (ml.m5.xlarge, sklearn image)       │
│  Charts  │             │    │                                 │
│          │             │    │ bootstrap.py                    │
│  Progress│             │    │   ├─ pip install lightgbm...    │
│  Bar     │             │    │   └─ run_training()             │
└──────────┘             │    │                                 │
     ▲                   │    ▼                                 │
     │                   │  S3: openoptions-ml/jobs/{name}/     │
     │                   │    ├─ progress.json                  │
     │                   │    ├─ epochs/100.json, 200.json...   │
     │                   │    └─ metrics.json (final)           │
     │                   │    ▲                                 │
     │                   │    │ reads every 60s                 │
     │                   │  Poller Lambda (EventBridge)         │
     │                   │    │                                 │
     │                   │    ▼                                 │
     │                   │  RDS (PostgreSQL)                    │
     │                   │    ├─ ml_runs (status, progress)     │
     │                   │    └─ ml_epoch_metrics (loss data)   │
     │                   └──────────────────────────────────────┘
     │                              │
     └──────────────── API ─────────┘
                    GET /ml/overview
                    GET /ml/runs/{id}/metrics
```

## Component Responsibilities

### ML Pipeline (`ml/`)

| Component | Files | Purpose |
|---|---|---|
| **Config** | `config/settings.py` | Pydantic settings with `ML_` env prefix |
| **Data** | `data/download.py` | Numerai data download via numerapi |
| **Features** | `data/features.py`, `data/garch.py` | Feature engineering (era stats, groups, GARCH) |
| **Models** | `models/lgbm_model.py`, `models/base.py` | LightGBM training with era-aware CV |
| **Training** | `training/trainer.py` | Pipeline orchestrator |
| **Validation** | `training/validate.py` | Numerai metrics (correlation, Sharpe, etc.) |
| **Submission** | `training/submission.py` | CSV generation and Numerai upload |
| **SageMaker** | `bootstrap.py`, `sagemaker/launch_job.py` | Cloud training entry point and launcher |

### Backend Services (`backend/`)

| Component | Files | Purpose |
|---|---|---|
| **SageMaker Service** | `app/services/sagemaker_service.py` | boto3 wrapper for SageMaker API |
| **ML Router** | `app/routers/ml.py` | REST endpoints for training, experiments, runs |
| **Poller Lambda** | `sagemaker_poller/handler.py` | Syncs S3 progress to RDS every 60s |
| **SAM Template** | `template.yaml` | CloudFormation: Lambda functions, IAM, EventBridge |

### Frontend (`frontend/`)

| Component | Files | Purpose |
|---|---|---|
| **ML Page** | `src/routes/ml/+page.svelte` | 4-tab dashboard (Overview, Experiments, Models, Rounds) |
| **Train Modal** | `src/lib/components/ml/TrainConfigModal.svelte` | Training configuration form |
| **Progress** | `src/lib/components/ml/TrainingProgress.svelte` | Active run display with progress |
| **Stores** | `src/lib/ml-stores.ts` | State management and polling logic |
| **API Client** | `src/lib/api.ts` | Typed fetch wrappers |

## Data Flow

### Training Data

```
Numerai API (numerapi)
    │
    ▼
data_cache/
  ├── train_r{round}.parquet     (~2.3GB, ~2.7M rows)
  ├── validation_r{round}.parquet (~3.5GB, ~3.9M rows)
  ├── live_r{round}.parquet       (~5MB, ~5K rows)
  └── features_r{round}.json     (feature metadata)
```

### Progress Reporting (SageMaker)

```
bootstrap.py
    │
    ├─ progress_callback() ──► S3: progress.json
    │   {"step": "training", "progress_pct": 45,
    │    "target": "target_alpha_20", "target_idx": 2}
    │
    ├─ epoch_callback() ──► S3: epochs/100.json
    │   {"epoch": 100, "train_loss": 0.0497, "val_loss": 0.0498}
    │
    └─ final metrics ──► S3: metrics.json
        {"ensemble": {"mean_corr": 0.023, "sharpe": 1.1, ...}}
```

### Database Schema

```sql
ml_experiments
  ├── id, name, description, status, created_at

ml_runs
  ├── id, experiment_id (FK)
  ├── model_type, status, hyperparams_json
  ├── correlation, sharpe, feature_exposure, max_drawdown
  ├── progress_pct, current_epoch, total_epochs
  ├── sagemaker_job_name, sagemaker_job_arn, error_message
  └── started_at, finished_at, created_at

ml_epoch_metrics
  ├── id, run_id (FK)
  ├── epoch, train_loss, val_loss
  └── correlation, sharpe

ml_models
  ├── id, run_id (FK), name, model_type
  ├── s3_path, correlation, sharpe
  └── feature_exposure, max_drawdown

ml_rounds
  ├── id, round_number, model_id (FK)
  ├── correlation, sharpe, submission_id
  └── submitted_at

ml_ensembles
  ├── id, name, description
  └── model_ids, weights
```

## Design Decisions

### Why S3 for Progress (Not Direct RDS)

SageMaker containers run in isolated VPCs. To write directly to RDS, the container would need VPC access, which requires a NAT gateway (~$30/month). Instead, the container writes JSON files to S3 (free from SageMaker), and a Poller Lambda reads them every 60 seconds. This adds ~60s latency to progress updates but saves ongoing cost.

### Why sklearn Framework Image (Not Custom Docker)

The sklearn framework image (`sagemaker-scikit-learn:1.2-1-cpu-py3`) includes Python 3.9, pandas, numpy, scipy, and scikit-learn pre-installed. Our `bootstrap.py` only needs to pip-install 6 extra packages (~30s). This avoids maintaining a custom Docker image, ECR repository, and CI/CD pipeline. The trade-off is ~30s startup overhead per job, which is negligible for 1-2 hour training runs.

### Why Multi-Target Training

Numerai rewards diverse predictions. Training on 6 different target variants and ensembling via rank-average produces more robust predictions than training on the primary target alone. Each target captures different aspects of the underlying stock returns (e.g., different time horizons, risk factors).

### Why Feature Neutralization

Numerai penalizes predictions that are too correlated with known features (feature exposure). Neutralization via OLS residualization reduces this exposure at the cost of some raw correlation. The 50% proportion is a balance — too much neutralization kills the signal, too little leaves high exposure.
