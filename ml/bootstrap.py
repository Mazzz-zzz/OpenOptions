#!/usr/bin/env python3
"""SageMaker entry point — bootstrap script.

The sklearn framework extracts the source tarball to /opt/ml/code/ and runs
this file. It installs extra dependencies then delegates to run_training().
"""
import json
import os
import subprocess
import sys

# Upgrade numpy+pandas together to avoid ABI mismatch, then install extras
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
    "--upgrade", "numpy", "pandas", "pyarrow"])
subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
    "lightgbm", "numerapi", "pyyaml", "pydantic", "pydantic-settings"])

# Parse hyperparameters from SageMaker config
hp_path = "/opt/ml/input/config/hyperparameters.json"
with open(hp_path) as f:
    hp = {k: v.strip('"') for k, v in json.load(f).items()}

feature_set = hp.get("feature_set", "small")
s3_bucket = hp.get("s3_bucket", "openoptions-ml")
job_name = hp.get("job_name", "unknown")
upload = hp.get("upload", "false").lower() == "true"

# Forward hyperparams as ML_ env vars so MlSettings picks them up
HP_TO_ENV = {
    "num_rounds": "ML_DEFAULT_NUM_ROUNDS",
    "learning_rate": "ML_DEFAULT_LEARNING_RATE",
    "num_leaves": "ML_DEFAULT_NUM_LEAVES",
    "max_depth": "ML_DEFAULT_MAX_DEPTH",
    "feature_fraction": "ML_DEFAULT_FEATURE_FRACTION",
    "bagging_fraction": "ML_DEFAULT_BAGGING_FRACTION",
    "early_stopping_rounds": "ML_EARLY_STOPPING_ROUNDS",
    "max_train_eras": "ML_MAX_TRAIN_ERAS",
    "neutralization_proportion": "ML_NEUTRALIZATION_PROPORTION",
    "multi_target_enabled": "ML_MULTI_TARGET_ENABLED",
    "enable_era_stats": "ML_ENABLE_ERA_STATS",
    "enable_group_aggregates": "ML_ENABLE_GROUP_AGGREGATES",
}
for hp_key, env_key in HP_TO_ENV.items():
    if hp_key in hp:
        os.environ[env_key] = hp[hp_key]

print(f"Starting training: feature_set={feature_set}, job_name={job_name}, upload={upload}")
overrides = {k: hp[k] for k in HP_TO_ENV if k in hp}
if overrides:
    print(f"  Hyperparam overrides: {overrides}")

import boto3


def write_s3_json(bucket, key, data):
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key,
                  Body=json.dumps(data, default=str),
                  ContentType="application/json")


def progress_callback(info):
    try:
        write_s3_json(s3_bucket, f"jobs/{job_name}/progress.json", info)
    except Exception as e:
        print(f"Warning: progress write failed: {e}")


def epoch_callback(info):
    try:
        epoch = info.get("epoch", 0)
        write_s3_json(s3_bucket, f"jobs/{job_name}/epochs/{epoch}.json", info)
    except Exception as e:
        print(f"Warning: epoch write failed: {e}")


from training.trainer import run_training

model_dir = os.environ.get("SM_MODEL_DIR", "/opt/ml/model")
metrics = run_training(
    feature_set_name=feature_set,
    output_dir=model_dir,
    skip_download=False,
    upload=upload,
    progress_callback=progress_callback,
    epoch_callback=epoch_callback,
)

write_s3_json(s3_bucket, f"jobs/{job_name}/metrics.json", metrics)
print("Training complete!")
