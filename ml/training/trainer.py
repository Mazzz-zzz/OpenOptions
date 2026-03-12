"""CLI entry point for Numerai training pipeline.

Usage:
    python -m training.trainer --model lgbm --output ./output

Phase 1: LightGBM only. Phase 2 will add more models.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Add ml/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_ml_settings
from data.download import download_current_round, load_train_data, load_validation_data
from data.features import add_era_stats, get_feature_columns
from models.lgbm_model import LightGBMModel
from training.validate import compute_all_metrics


def run_training(
    model_type: str = "lgbm",
    output_dir: str = "./output",
    skip_download: bool = False,
    **model_kwargs,
) -> dict:
    """Full training pipeline: download -> features -> train -> validate.

    Returns a dict of validation metrics.
    """
    settings = get_ml_settings()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # 1. Download data
    if not skip_download:
        print("Downloading Numerai data...")
        download_current_round()

    # 2. Load data
    print("Loading training data...")
    train_df = load_train_data()
    val_df = load_validation_data()

    # 3. Feature engineering
    feature_cols = get_feature_columns(train_df, settings.feature_prefix)
    print(f"Found {len(feature_cols)} features")

    # Add era-level statistics for a subset of features (top 50 by variance)
    if len(feature_cols) > 50:
        variances = train_df[feature_cols].var().nlargest(50)
        era_features = variances.index.tolist()
    else:
        era_features = feature_cols

    train_df = add_era_stats(train_df, era_features, settings.era_col)
    val_df = add_era_stats(val_df, era_features, settings.era_col)

    # Update feature cols to include new features
    all_features = get_feature_columns(train_df, settings.feature_prefix)
    era_derived = [c for c in train_df.columns if "_era_" in c]
    all_features = all_features + era_derived

    # 4. Train model
    print(f"Training {model_type} model...")
    if model_type == "lgbm":
        model = LightGBMModel(**model_kwargs)
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    train_info = model.fit(
        train_df, all_features, settings.target_col, settings.era_col
    )
    print(f"Training complete: {train_info}")

    # 5. Validate
    print("Validating...")
    val_df["prediction"] = model.predict(val_df, all_features)
    metrics = compute_all_metrics(
        val_df, "prediction", settings.target_col, settings.era_col, all_features
    )
    print(f"Validation metrics: {json.dumps(metrics, indent=2)}")

    # 6. Save model
    model_path = output_path / f"{model_type}_model"
    model.save(model_path)
    print(f"Model saved to {model_path}")

    # Save metrics
    with open(output_path / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def main():
    parser = argparse.ArgumentParser(description="Numerai ML Training Pipeline")
    parser.add_argument("--model", default="lgbm", choices=["lgbm"])
    parser.add_argument("--output", default="./output")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--n-estimators", type=int, default=2000)
    args = parser.parse_args()

    run_training(
        model_type=args.model,
        output_dir=args.output,
        skip_download=args.skip_download,
        num_leaves=args.num_leaves,
        learning_rate=args.learning_rate,
        n_estimators=args.n_estimators,
    )


if __name__ == "__main__":
    main()
