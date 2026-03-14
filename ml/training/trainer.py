"""CLI entry point for Numerai training pipeline.

Usage:
    python -m training.trainer --feature-set medium --output ./output
    python -m training.trainer --feature-set small --output ./output --upload

Pipeline:
    1. Download data (anonymous, no credentials needed)
    2. Load feature metadata and select feature set
    3. Load data with column filtering (RAM-efficient)
    4. Feature engineering (era stats, group aggregates)
    5. Multi-target LightGBM training
    6. Ensemble (rank-average across target models)
    7. Feature neutralization
    8. Validation metrics
    9. Live predictions + submission CSV
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# Add ml/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_ml_settings
from data.download import (
    download_current_round,
    get_current_round,
    get_feature_set,
    load_benchmark_models,
    load_feature_metadata,
    load_live_data,
    load_meta_model,
    load_train_data,
    load_validation_data,
)
from data.features import (
    add_era_stats,
    add_group_aggregates,
    discover_feature_groups,
    get_feature_columns,
    neutralize_features,
)
from models.lgbm_model import LightGBMModel
from training.submission import generate_submission, validate_submission
from training.validate import compute_all_metrics


def _build_columns_to_load(
    feature_cols: List[str],
    target_cols: List[str],
    era_col: str,
) -> List[str]:
    """Build the list of columns to load from parquet (saves RAM)."""
    cols = list(feature_cols) + [era_col]
    for t in target_cols:
        if t not in cols:
            cols.append(t)
    return cols


def _apply_feature_engineering(
    df: pd.DataFrame,
    feature_cols: List[str],
    feature_groups: Dict[str, List[str]],
    settings,
    era_stat_features: Optional[List[str]] = None,
) -> tuple:
    """Apply feature engineering in-place.

    Returns (all_features, era_stat_features) so the same era_stat_features
    can be passed when engineering validation/live data.
    """
    all_features = list(feature_cols)

    if settings.enable_era_stats:
        if era_stat_features is None:
            # Compute top N features by variance (only from training data)
            n = min(settings.era_stats_top_n, len(feature_cols))
            variances = df[feature_cols].var().nlargest(n)
            era_stat_features = variances.index.tolist()

        add_era_stats(df, era_stat_features, settings.era_col)
        era_derived = [c for c in df.columns if "_era_" in c]
        all_features.extend(era_derived)

    if settings.enable_group_aggregates and feature_groups:
        add_group_aggregates(df, feature_groups)
        group_derived = [c for c in df.columns if c.startswith("group_")]
        all_features.extend(c for c in group_derived if c not in all_features)

    return all_features, era_stat_features


def _rank_normalize(series: pd.Series) -> pd.Series:
    """Rank-normalize a Series to [0, 1]."""
    return series.rank(pct=True, method="average")


def _ensemble_predictions(
    predictions: Dict[str, pd.Series],
) -> pd.Series:
    """Rank-average ensemble across multiple target models."""
    if not predictions:
        raise ValueError("No predictions to ensemble")

    if len(predictions) == 1:
        return next(iter(predictions.values()))

    ranked = pd.DataFrame({
        name: _rank_normalize(preds)
        for name, preds in predictions.items()
    })
    ensemble = ranked.mean(axis=1)
    ensemble.name = "prediction"
    return ensemble


def run_training(
    feature_set_name: str = "medium",
    output_dir: str = "./output",
    skip_download: bool = False,
    upload: bool = False,
    progress_callback: Optional[Callable[[dict], None]] = None,
    epoch_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Full training pipeline.

    Returns a dict of validation metrics.
    """
    settings = get_ml_settings()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    def _progress(step: str, progress_pct: float, **extra):
        if progress_callback:
            progress_callback({"step": step, "progress_pct": progress_pct, **extra})

    # 1. Download data
    round_num = None
    _progress("downloading", 5)
    if not skip_download:
        print("Step 1: Downloading Numerai data...")
        data_dir = download_current_round()
    else:
        print("Step 1: Skipping download (using cached data)")
        data_dir = None  # uses default DATA_DIR

    # 2. Feature metadata
    _progress("loading_metadata", 10)
    print("Step 2: Loading feature metadata...")
    metadata = load_feature_metadata(data_dir)
    feature_cols = get_feature_set(metadata, feature_set_name)
    print(f"  Feature set '{feature_set_name}': {len(feature_cols)} features")

    # Determine which targets exist
    target_cols = settings.target_cols if settings.multi_target_enabled else [settings.target_col]

    # 3. Load data with column filtering
    print("Step 3: Loading training data...")
    load_cols = _build_columns_to_load(feature_cols, target_cols, settings.era_col)
    train_df = load_train_data(data_dir, columns=load_cols)

    # Subsample eras for memory management
    if settings.max_train_eras > 0:
        all_eras = sorted(train_df[settings.era_col].unique())
        keep_eras = all_eras[-settings.max_train_eras:]
        train_df = train_df[train_df[settings.era_col].isin(keep_eras)]
        print(f"  Subsampled to {settings.max_train_eras} most recent eras")

    print(f"  Train: {train_df.shape[0]:,} rows, {train_df.shape[1]} columns")

    val_df = load_validation_data(data_dir, columns=load_cols)

    if settings.max_train_eras > 0:
        val_eras = sorted(val_df[settings.era_col].unique())
        keep_val_eras = val_eras[-min(settings.max_train_eras, len(val_eras)):]
        val_df = val_df[val_df[settings.era_col].isin(keep_val_eras)]

    print(f"  Validation: {val_df.shape[0]:,} rows")

    # Filter to targets actually present in data
    available_targets = [t for t in target_cols if t in train_df.columns]
    skipped_targets = [t for t in target_cols if t not in train_df.columns]
    if skipped_targets:
        print(f"  Skipping targets not in data: {skipped_targets}")
    print(f"  Training targets: {available_targets}")

    # 4. Feature engineering
    _progress("feature_engineering", 15)
    print("Step 4: Feature engineering...")
    feature_groups = discover_feature_groups(metadata, feature_cols)
    print(f"  Found {len(feature_groups)} feature groups")

    all_features, era_stat_features = _apply_feature_engineering(
        train_df, feature_cols, feature_groups, settings
    )
    _apply_feature_engineering(
        val_df, feature_cols, feature_groups, settings,
        era_stat_features=era_stat_features,
    )
    print(f"  Total features after engineering: {len(all_features)}")

    # 5. Multi-target training
    print("Step 5: Training models...")
    models = {}
    train_infos = {}
    val_predictions = {}

    for target_idx, target in enumerate(available_targets):
        # Skip targets with too many NaNs
        target_nans = train_df[target].isna().sum()
        if target_nans > len(train_df) * 0.5:
            print(f"  Skipping {target} ({target_nans} NaN rows)")
            continue

        _progress(
            "training", 20 + (60 * target_idx / len(available_targets)),
            target=target, target_idx=target_idx, total_targets=len(available_targets),
        )
        print(f"  Training on {target}...")
        # Drop rows with NaN target for this model
        mask = train_df[target].notna()
        train_subset = train_df[mask]

        model = LightGBMModel(
            num_leaves=settings.default_num_leaves,
            max_depth=settings.default_max_depth,
            learning_rate=settings.default_learning_rate,
            n_estimators=settings.default_num_rounds,
            feature_fraction=settings.default_feature_fraction,
            bagging_fraction=settings.default_bagging_fraction,
            early_stopping_rounds=settings.early_stopping_rounds,
        )

        info = model.fit(
            train_subset, all_features, target, settings.era_col,
            epoch_callback=epoch_callback,
        )
        models[target] = model
        train_infos[target] = info
        print(f"    Best iteration: {info['best_iteration']}")

        # Validation predictions
        val_mask = val_df[target].notna()
        val_predictions[target] = model.predict(val_df[val_mask], all_features)

        # Save individual model
        model_path = output_path / f"model_{target}"
        model.save(model_path)

    if not models:
        raise RuntimeError("No models were trained — check target columns")

    # 6. Ensemble
    print("Step 6: Ensemble predictions...")
    # For ensemble, only use rows where all models have predictions
    common_idx = val_df.index
    for preds in val_predictions.values():
        common_idx = common_idx.intersection(preds.index)

    aligned_preds = {
        name: preds.loc[common_idx]
        for name, preds in val_predictions.items()
    }
    ensemble_preds = _ensemble_predictions(aligned_preds)

    # 7. Neutralization
    _progress("neutralization", 82)
    print("Step 7: Feature neutralization...")
    val_common = val_df.loc[common_idx].copy()
    val_common["prediction"] = ensemble_preds.values

    neutralizer_cols = feature_cols[:settings.neutralization_top_n]
    neutralizer_cols = [c for c in neutralizer_cols if c in val_common.columns]

    if neutralizer_cols and settings.neutralization_proportion > 0:
        val_common["prediction"] = neutralize_features(
            val_common,
            "prediction",
            neutralizer_cols,
            proportion=settings.neutralization_proportion,
        )
        print(f"  Neutralized against {len(neutralizer_cols)} features "
              f"(proportion={settings.neutralization_proportion})")

    # 8. Validation
    _progress("validation", 85)
    print("Step 8: Validation metrics...")

    # Load meta model and benchmarks for advanced validation
    meta_model_col = None
    benchmark_cols = None
    try:
        meta_df = load_meta_model(data_dir)
        if meta_df is not None:
            # Join meta model predictions (available era 1133+)
            common_ids = val_common.index.intersection(meta_df.index)
            if len(common_ids) > 0:
                val_common = val_common.loc[common_ids].copy()
                val_common["numerai_meta_model"] = meta_df.loc[common_ids, "numerai_meta_model"]
                meta_model_col = "numerai_meta_model"
                print(f"  Meta model joined: {len(common_ids):,} rows (era 1133+)")
    except Exception as e:
        print(f"  Meta model not available: {e}")

    try:
        bm_df = load_benchmark_models(data_dir)
        if bm_df is not None:
            common_ids = val_common.index.intersection(bm_df.index)
            if len(common_ids) > 0:
                bm_cols = [c for c in bm_df.columns if c.startswith("v52_lgbm_")]
                for col in bm_cols:
                    val_common.loc[common_ids, col] = bm_df.loc[common_ids, col]
                benchmark_cols = bm_cols
                print(f"  Benchmarks joined: {len(bm_cols)} models")
    except Exception as e:
        print(f"  Benchmarks not available: {e}")

    metrics = compute_all_metrics(
        val_common, "prediction", settings.target_col, settings.era_col,
        feature_cols=[c for c in neutralizer_cols if c in val_common.columns],
        meta_model_col=meta_model_col,
        benchmark_cols=benchmark_cols,
    )
    print(f"  Ensemble metrics: {json.dumps(metrics, indent=2)}")

    # Per-target metrics
    per_target_metrics = {}
    for target, preds in val_predictions.items():
        target_df = val_df.loc[preds.index].copy()
        target_df["prediction"] = preds.values
        per_target_metrics[target] = compute_all_metrics(
            target_df, "prediction", target, settings.era_col,
        )

    all_metrics = {
        "ensemble": metrics,
        "per_target": per_target_metrics,
        "feature_set": feature_set_name,
        "n_features": len(all_features),
        "n_models": len(models),
        "training_info": {k: {"best_iteration": v["best_iteration"]} for k, v in train_infos.items()},
    }

    with open(output_path / "metrics.json", "w") as f:
        json.dump(all_metrics, f, indent=2)

    # 9. Live predictions + submission
    _progress("live_predictions", 90)
    print("Step 9: Live predictions...")
    try:
        live_cols = _build_columns_to_load(feature_cols, [], settings.era_col)
        live_df = load_live_data(data_dir, columns=live_cols)
        print(f"  Live data: {live_df.shape[0]:,} rows")

        # Apply same feature engineering (use same era_stat_features as training)
        _apply_feature_engineering(
            live_df, feature_cols, feature_groups, settings,
            era_stat_features=era_stat_features,
        )

        # Predict with all models
        live_predictions = {}
        for target, model in models.items():
            live_predictions[target] = model.predict(live_df, all_features)

        live_ensemble = _ensemble_predictions(live_predictions)

        # Neutralize live predictions
        if neutralizer_cols and settings.neutralization_proportion > 0:
            live_df_copy = live_df.copy()
            live_df_copy["prediction"] = live_ensemble.values
            live_ensemble = neutralize_features(
                live_df_copy,
                "prediction",
                neutralizer_cols,
                proportion=settings.neutralization_proportion,
            )

        # Get round number
        try:
            round_num = get_current_round()
        except Exception:
            round_num = None

        csv_path = generate_submission(live_ensemble, output_path, round_num)
        validate_submission(csv_path, expected_ids=live_df.index)
        print(f"  Submission written: {csv_path}")

    except FileNotFoundError:
        print("  No live data found — skipping submission generation")
        csv_path = None

    # 10. Optional upload
    if upload and csv_path:
        if not settings.numerai_public_id or not settings.numerai_secret_key:
            print("  Upload requested but credentials not set "
                  "(ML_NUMERAI_PUBLIC_ID / ML_NUMERAI_SECRET_KEY)")
        else:
            from training.submission import upload_submission
            sid = upload_submission(
                csv_path,
                settings.numerai_public_id,
                settings.numerai_secret_key,
                settings.numerai_model_id,
            )
            print(f"  Uploaded! Submission ID: {sid}")

    _progress("completed", 100)
    print("Done.")
    return all_metrics


def main():
    parser = argparse.ArgumentParser(description="Numerai ML Training Pipeline")
    parser.add_argument(
        "--feature-set", default="medium",
        help="Feature set: small (42), medium (705), all (2376)",
    )
    parser.add_argument("--output", default="./output")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--upload", action="store_true",
        help="Upload submission to Numerai (requires credentials)",
    )
    args = parser.parse_args()

    run_training(
        feature_set_name=args.feature_set,
        output_dir=args.output,
        skip_download=args.skip_download,
        upload=args.upload,
    )


if __name__ == "__main__":
    main()
