"""Poller Lambda — syncs SageMaker job status to RDS.

Triggered by EventBridge every 60 seconds. For each active ml_run with a
sagemaker_job_name, it:
1. Describes the SageMaker job to get status
2. Reads progress.json from S3
3. Reads new epoch metric files from S3
4. Updates the ml_runs row and inserts epoch metrics
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3
import psycopg2
import psycopg2.extras

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get("ML_S3_BUCKET", "openoptions-ml")

# SageMaker on-demand hourly rates (ap-southeast-2, USD)
INSTANCE_HOURLY_RATES = {
    "ml.m5.large": 0.134,
    "ml.m5.xlarge": 0.269,
    "ml.m5.2xlarge": 0.538,
    "ml.m5.4xlarge": 1.075,
    "ml.c5.xlarge": 0.235,
    "ml.c5.2xlarge": 0.470,
    "ml.c5.4xlarge": 0.941,
    "ml.p3.2xlarge": 4.284,
    "ml.g4dn.xlarge": 0.821,
    "ml.g5.xlarge": 1.408,
}


def _get_db_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "openoptions"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"],
    )


def _read_s3_json(s3, bucket: str, key: str) -> dict | None:
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        logger.warning("Failed to read s3://%s/%s: %s", bucket, key, e)
        return None


def _list_epoch_files(s3, bucket: str, prefix: str) -> list[str]:
    """List epoch JSON files under a prefix."""
    keys = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".json"):
                    keys.append(obj["Key"])
    except Exception as e:
        logger.warning("Failed to list s3://%s/%s: %s", bucket, prefix, e)
    return keys


def _sm_status_to_run_status(sm_status: str) -> str:
    mapping = {
        "InProgress": "running",
        "Completed": "completed",
        "Failed": "failed",
        "Stopped": "failed",
        "Stopping": "running",
    }
    return mapping.get(sm_status, "pending")


def handler(event, context):
    conn = _get_db_conn()
    sm = boto3.client("sagemaker", region_name="ap-southeast-2")
    s3 = boto3.client("s3")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Find active runs with SageMaker jobs
            cur.execute(
                "SELECT id, sagemaker_job_name, experiment_id, model_type FROM ml_runs "
                "WHERE status IN ('pending', 'running') "
                "AND sagemaker_job_name IS NOT NULL"
            )
            active_runs = cur.fetchall()

            if not active_runs:
                logger.info("No active SageMaker runs")
                return {"processed": 0}

            logger.info("Processing %d active runs", len(active_runs))

            for row in active_runs:
                run_id = row["id"]
                job_name = row["sagemaker_job_name"]
                experiment_id = row["experiment_id"]
                model_type = row["model_type"]

                try:
                    _process_run(cur, sm, s3, run_id, job_name, experiment_id, model_type)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    logger.exception("Failed to process run %d (%s)", run_id, job_name)

        return {"processed": len(active_runs)}

    finally:
        conn.close()


def _register_model(cur, run_id, experiment_id, model_type, job_name,
                    correlation, sharpe, feature_exposure=None, max_drawdown=None, mmc=None):
    """Auto-register a model when a training run completes successfully."""
    # Get experiment name for the model name
    cur.execute("SELECT name FROM ml_experiments WHERE id = %s", (experiment_id,))
    row = cur.fetchone()
    exp_name = row["name"] if row else "unknown"

    model_name = f"{exp_name}-run{run_id}"

    # Check if already registered (idempotent)
    cur.execute("SELECT id FROM ml_models WHERE run_id = %s", (run_id,))
    if cur.fetchone():
        return

    cur.execute(
        "INSERT INTO ml_models (name, model_type, run_id, correlation, sharpe, feature_exposure, max_drawdown, mmc) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (model_name, model_type, run_id, correlation, sharpe, feature_exposure, max_drawdown, mmc),
    )
    logger.info("Registered model %s for run %d", model_name, run_id)


def _process_run(cur, sm, s3, run_id: int, job_name: str, experiment_id: int = 0, model_type: str = "lgbm"):
    """Process a single active run."""
    # 1. Describe SageMaker job
    try:
        resp = sm.describe_training_job(TrainingJobName=job_name)
    except Exception:
        logger.exception("Failed to describe job %s", job_name)
        return

    sm_status = resp["TrainingJobStatus"]
    run_status = _sm_status_to_run_status(sm_status)

    # 2. Read progress from S3
    progress = _read_s3_json(s3, S3_BUCKET, f"jobs/{job_name}/progress.json")

    # Build update fields
    updates = {"status": run_status}

    if progress:
        if "progress_pct" in progress:
            updates["progress_pct"] = progress["progress_pct"]
        if "step" in progress:
            # Store step info in progress for frontend
            pass

    if resp.get("TrainingStartTime"):
        updates["started_at"] = resp["TrainingStartTime"].isoformat()

    # Store instance type from ResourceConfig
    resource_config = resp.get("ResourceConfig", {})
    inst_type = resource_config.get("InstanceType")
    if inst_type:
        updates["instance_type"] = inst_type

    if sm_status == "Completed":
        updates["progress_pct"] = 100
        if resp.get("TrainingEndTime"):
            updates["finished_at"] = resp["TrainingEndTime"].isoformat()

        # Compute cost from BillableSeconds
        billable_seconds = resp.get("BillableSeconds")
        if billable_seconds and inst_type:
            hourly_rate = INSTANCE_HOURLY_RATES.get(inst_type, 0)
            if hourly_rate:
                updates["cost_usd"] = round(billable_seconds * hourly_rate / 3600, 4)

        # Read final metrics
        metrics = _read_s3_json(s3, S3_BUCKET, f"jobs/{job_name}/metrics.json")
        if metrics:
            ensemble = metrics.get("ensemble", {})
            updates["correlation"] = ensemble.get("correlation")
            updates["sharpe"] = ensemble.get("sharpe")
            updates["feature_exposure"] = ensemble.get("feature_exposure")
            updates["max_drawdown"] = ensemble.get("max_drawdown")
            updates["mmc"] = ensemble.get("mmc")

            # Auto-register model
            _register_model(
                cur, run_id, experiment_id, model_type, job_name,
                ensemble.get("correlation"), ensemble.get("sharpe"),
                ensemble.get("feature_exposure"), ensemble.get("max_drawdown"),
                ensemble.get("mmc"),
            )

    if sm_status == "Failed":
        updates["error_message"] = (resp.get("FailureReason") or "Unknown error")[:2000]
        if resp.get("TrainingEndTime"):
            updates["finished_at"] = resp["TrainingEndTime"].isoformat()
        # Still compute cost for failed jobs
        billable_seconds = resp.get("BillableSeconds")
        if billable_seconds and inst_type:
            hourly_rate = INSTANCE_HOURLY_RATES.get(inst_type, 0)
            if hourly_rate:
                updates["cost_usd"] = round(billable_seconds * hourly_rate / 3600, 4)

    if sm_status == "Stopped":
        updates["error_message"] = "Job stopped"
        if resp.get("TrainingEndTime"):
            updates["finished_at"] = resp["TrainingEndTime"].isoformat()
        billable_seconds = resp.get("BillableSeconds")
        if billable_seconds and inst_type:
            hourly_rate = INSTANCE_HOURLY_RATES.get(inst_type, 0)
            if hourly_rate:
                updates["cost_usd"] = round(billable_seconds * hourly_rate / 3600, 4)

    # 3. Read and insert epoch metrics
    epoch_keys = _list_epoch_files(s3, S3_BUCKET, f"jobs/{job_name}/epochs/")

    # Get existing epochs to avoid duplicates
    cur.execute(
        "SELECT epoch FROM ml_epoch_metrics WHERE run_id = %s",
        (run_id,),
    )
    existing_epochs = {r[0] for r in cur.fetchall()}

    max_epoch = max(existing_epochs) if existing_epochs else 0

    for key in epoch_keys:
        data = _read_s3_json(s3, S3_BUCKET, key)
        if not data:
            continue

        # Use global_epoch (continuous across targets) if available, else epoch
        epoch = data.get("global_epoch", data.get("epoch"))
        if epoch is None or epoch in existing_epochs:
            continue

        cur.execute(
            "INSERT INTO ml_epoch_metrics (run_id, epoch, train_loss, val_loss, correlation, sharpe) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, epoch) DO NOTHING",
            (
                run_id,
                epoch,
                data.get("train_loss"),
                data.get("val_loss"),
                data.get("correlation"),
                data.get("sharpe"),
            ),
        )
        existing_epochs.add(epoch)
        if epoch > max_epoch:
            max_epoch = epoch

    # Set current_epoch and total_epochs from epoch data + hyperparams
    if existing_epochs:
        updates["current_epoch"] = max_epoch
        hyperparams = resp.get("HyperParameters", {})
        num_rounds = hyperparams.get("num_rounds")
        if num_rounds:
            try:
                updates["total_epochs"] = int(num_rounds)
            except (ValueError, TypeError):
                pass

    # 4. Update ml_runs row
    set_clauses = []
    values = []
    for col, val in updates.items():
        if val is not None:
            set_clauses.append(f"{col} = %s")
            values.append(val)

    if set_clauses:
        values.append(run_id)
        cur.execute(
            f"UPDATE ml_runs SET {', '.join(set_clauses)} WHERE id = %s",
            values,
        )

    logger.info(
        "Run %d: sm_status=%s, run_status=%s, epochs=%d, current_epoch=%s",
        run_id, sm_status, run_status, len(epoch_keys), max_epoch,
    )
