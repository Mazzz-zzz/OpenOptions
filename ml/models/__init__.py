"""Model factory for Numerai tournament models."""

from __future__ import annotations

from typing import Optional

from models.base import NumeraiModel
from models.lgbm_model import LightGBMModel

# Optional imports - models that may not be installed
try:
    from models.catboost_model import CatBoostModel
except ImportError:
    CatBoostModel = None


def create_model(
    model_type: str = "lgbm",
    num_leaves: int = 512,
    max_depth: int = 8,
    learning_rate: float = 0.005,
    n_estimators: int = 10000,
    feature_fraction: float = 0.1,
    bagging_fraction: float = 0.5,
    bagging_freq: int = 1,
    early_stopping_rounds: int = 200,
    **kwargs,
) -> NumeraiModel:
    """Factory function to create a model instance by type.
    
    Args:
        model_type: "lgbm" or "catboost"
        num_leaves: LightGBM num_leaves (used for LGBM only)
        max_depth: Max tree depth (used for both)
        learning_rate: Learning rate (used for both)
        n_estimators: Number of boosting rounds/iterations
        feature_fraction: LightGBM feature_fraction (column sampling)
        bagging_fraction: LightGBM bagging_fraction (row sampling)
        bagging_freq: LightGBM bagging frequency
        early_stopping_rounds: Early stopping patience
        **kwargs: Additional model-specific parameters
    
    Returns:
        NumeraiModel instance
    
    Raises:
        ValueError: If model_type is not supported
        RuntimeError: If required package not installed
    """
    model_type = model_type.lower()
    
    if model_type == "lgbm":
        return LightGBMModel(
            num_leaves=num_leaves,
            max_depth=max_depth,
            learning_rate=learning_rate,
            n_estimators=n_estimators,
            feature_fraction=feature_fraction,
            bagging_fraction=bagging_fraction,
            bagging_freq=bagging_freq,
            early_stopping_rounds=early_stopping_rounds,
            **kwargs,
        )
    
    elif model_type == "catboost":
        if CatBoostModel is None:
            raise RuntimeError(
                "CatBoost not installed. "
                "Install with: pip install catboost"
            )
        # Map LightGBM params to CatBoost equivalents
        return CatBoostModel(
            iterations=n_estimators,
            learning_rate=learning_rate,
            depth=max_depth,
            early_stopping_rounds=early_stopping_rounds,
            **kwargs,
        )
    
    else:
        raise ValueError(
            f"Unknown model_type: {model_type}. "
            f"Supported types: lgbm, catboost"
        )


def list_available_models() -> list[str]:
    """Return list of available model types."""
    models = ["lgbm"]
    if CatBoostModel is not None:
        models.append("catboost")
    return models
