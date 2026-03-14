"""Pydantic settings for ML training pipeline."""

from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings


class MlSettings(BaseSettings):
    # Numerai credentials (only needed for upload, not data download)
    numerai_public_id: str = ""
    numerai_secret_key: str = ""
    numerai_model_id: str = ""

    # S3 storage for models and data
    s3_bucket: str = "openoptions-ml"
    s3_prefix: str = "numerai/"

    # LightGBM training defaults — production settings
    default_model_type: str = "lgbm"
    default_num_rounds: int = 10000
    default_learning_rate: float = 0.005
    default_num_leaves: int = 512
    default_max_depth: int = 8
    default_feature_fraction: float = 0.1
    default_bagging_fraction: float = 0.5
    early_stopping_rounds: int = 200

    # Feature set: "small" (42), "medium" (705), "all" (2376)
    feature_set: str = "medium"

    # Feature engineering toggles
    enable_era_stats: bool = True
    enable_group_aggregates: bool = True
    enable_rolling_features: bool = False
    enable_garch: bool = False

    # Era stats: top N features by variance
    era_stats_top_n: int = 30

    # Multi-target training — 8 targets including v5.2 Ender/Jasper
    multi_target_enabled: bool = True
    target_cols: List[str] = [
        "target",
        "target_cyrusd_20",
        "target_alpha_20",
        "target_bravo_20",
        "target_caroline_20",
        "target_delta_20",
        "target_ender_20",
        "target_jasper_20",
    ]

    # Feature neutralization
    neutralization_proportion: float = 0.5
    neutralization_top_n: int = 50

    # Memory management — 0 = all eras; 400 fits in 32GB with medium features
    max_train_eras: int = 400

    # Column identifiers
    era_col: str = "era"
    target_col: str = "target"
    feature_prefix: str = "feature_"

    # Database (for logging results)
    db_url: str = ""

    class Config:
        env_prefix = "ML_"


def get_ml_settings() -> MlSettings:
    return MlSettings()
