"""Launch a SageMaker training job.

Packages ml/ code into a tarball, uploads to S3, and creates a SageMaker
training job that unpacks the code, installs dependencies, and runs training.

Uses a bootstrap entry point that:
1. Unpacks the source tarball from the S3 input channel
2. pip-installs lightgbm, numerapi, etc.
3. Runs sagemaker/train_entry.py

Usage:
    cd ml/
    python3 sagemaker/launch_job.py --feature-set small
    python3 sagemaker/launch_job.py --feature-set medium --instance ml.m5.2xlarge
"""

from __future__ import annotations

import argparse
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import boto3

REGION = "ap-southeast-2"
ACCOUNT_ID = "017915195458"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/openoptions-sagemaker-execution"
S3_BUCKET = "openoptions-ml"

# SageMaker sklearn framework image for ap-southeast-2
# This has Python 3.10, pandas, numpy, scipy, scikit-learn pre-installed
# We add lightgbm + numerapi via the bootstrap script
SKLEARN_IMAGE = "783357654285.dkr.ecr.ap-southeast-2.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"


def _package_source(ml_dir: Path) -> str:
    """Package ml/ code (including bootstrap.py) into a tarball and upload to S3."""
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
        tmp_path = f.name

    with tarfile.open(tmp_path, "w:gz") as tar:
        for item in ml_dir.iterdir():
            if item.name in ("data_cache", "output", "__pycache__", ".env"):
                continue
            tar.add(item, arcname=item.name)

    s3 = boto3.client("s3", region_name=REGION)
    s3_key = "code/ml-source.tar.gz"
    s3.upload_file(tmp_path, S3_BUCKET, s3_key)
    os.unlink(tmp_path)

    return f"s3://{S3_BUCKET}/{s3_key}"


def launch(feature_set: str, instance_type: str, upload: bool = False):
    """Launch a SageMaker training job."""
    ml_dir = Path(__file__).parent.parent

    print("Packaging source code...")
    source_uri = _package_source(ml_dir)
    print(f"  Uploaded to {source_uri}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_name = f"oo-numerai-{feature_set}-{ts}"

    hyperparams = {
        "feature_set": feature_set,
        "s3_bucket": S3_BUCKET,
        "job_name": job_name,
    }

    # SageMaker sklearn framework mode: specify entry point + source dir
    # The framework unpacks source_dir and runs sagemaker_program
    sm_hyperparams = {
        **hyperparams,
        "sagemaker_program": "bootstrap.py",
        "sagemaker_submit_directory": f"s3://{S3_BUCKET}/code/ml-source.tar.gz",
    }

    sm = boto3.client("sagemaker", region_name=REGION)

    print(f"Creating training job: {job_name}")
    print(f"  Instance: {instance_type}")
    print(f"  Feature set: {feature_set}")
    print(f"  Image: {SKLEARN_IMAGE}")

    sm.create_training_job(
        TrainingJobName=job_name,
        AlgorithmSpecification={
            "TrainingImage": SKLEARN_IMAGE,
            "TrainingInputMode": "File",
        },
        RoleArn=ROLE_ARN,
        HyperParameters=sm_hyperparams,
        InputDataConfig=[
            {
                "ChannelName": "code",
                "DataSource": {
                    "S3DataSource": {
                        "S3DataType": "S3Prefix",
                        "S3Uri": source_uri,
                        "S3DataDistributionType": "FullyReplicated",
                    }
                },
                "CompressionType": "None",
                "InputMode": "File",
            }
        ],
        OutputDataConfig={
            "S3OutputPath": f"s3://{S3_BUCKET}/jobs/{job_name}/output",
        },
        ResourceConfig={
            "InstanceType": instance_type,
            "InstanceCount": 1,
            "VolumeSizeInGB": 50,
        },
        StoppingCondition={
            "MaxRuntimeInSeconds": 7200,
        },
        Environment={
            "ML_NUMERAI_PUBLIC_ID": os.environ.get("ML_NUMERAI_PUBLIC_ID", ""),
            "ML_NUMERAI_SECRET_KEY": os.environ.get("ML_NUMERAI_SECRET_KEY", ""),
        },
    )

    print(f"\nJob launched: {job_name}")
    print(f"Monitor:")
    print(f"  aws sagemaker describe-training-job --training-job-name {job_name} --region {REGION} --profile cybergarden-dev")
    print(f"Logs:")
    print(f"  aws logs tail /aws/sagemaker/TrainingJobs --log-stream-name-prefix {job_name} --region {REGION} --profile cybergarden-dev --follow")

    return job_name


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch SageMaker training job")
    parser.add_argument("--feature-set", default="small", choices=["small", "medium", "all"])
    parser.add_argument("--instance", default="ml.m5.xlarge")
    parser.add_argument("--upload", action="store_true", help="Upload submission to Numerai")
    args = parser.parse_args()

    # Load .env if present
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

    launch(args.feature_set, args.instance, args.upload)
