"""Pydantic settings for ML training pipeline."""

from pydantic_settings import BaseSettings


class MlSettings(BaseSettings):
    # Numerai credentials (stubbed — set via env vars when ready)
    numerai_public_id: str = ""
    numerai_secret_key: str = ""
    numerai_model_id: str = ""

    # S3 storage for models and data
    s3_bucket: str = "openoptions-ml"
    s3_prefix: str = "numerai/"

    # Training defaults
    default_model_type: str = "lgbm"
    default_num_rounds: int = 2000
    default_learning_rate: float = 0.01
    default_num_leaves: int = 31
    early_stopping_rounds: int = 100

    # Feature engineering
    era_col: str = "era"
    target_col: str = "target"
    feature_prefix: str = "feature_"

    # Database (for logging results)
    db_url: str = ""

    class Config:
        env_prefix = "ML_"


def get_ml_settings() -> MlSettings:
    return MlSettings()
