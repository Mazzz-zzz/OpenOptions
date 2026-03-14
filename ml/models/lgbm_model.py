"""LightGBM model with era-aware training for Numerai."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from models.base import NumeraiModel


class LightGBMModel(NumeraiModel):
    """LightGBM with era-based cross-validation and early stopping."""

    def __init__(
        self,
        num_leaves: int = 512,
        max_depth: int = 8,
        learning_rate: float = 0.005,
        n_estimators: int = 10000,
        feature_fraction: float = 0.1,
        bagging_fraction: float = 0.5,
        bagging_freq: int = 1,
        early_stopping_rounds: int = 200,
        **kwargs,
    ):
        self.n_estimators = n_estimators
        self.params = {
            "objective": "regression",
            "metric": "mse",
            "num_leaves": num_leaves,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "feature_fraction": feature_fraction,
            "bagging_fraction": bagging_fraction,
            "bagging_freq": bagging_freq,
            "verbose": -1,
            **kwargs,
        }
        self.early_stopping_rounds = early_stopping_rounds
        self._model: Optional[lgb.Booster] = None
        self._feature_names: List[str] = []

    @staticmethod
    def _make_epoch_callback(
        user_cb: Callable[[dict], None],
        every_n: int = 100,
    ):
        """Create a LightGBM callback that reports metrics every N rounds."""
        def callback(env):
            if env.iteration % every_n == 0:
                result = {"epoch": env.iteration}
                for name, metric_name, value, _ in env.evaluation_result_list:
                    result[f"{name}_{metric_name}"] = value
                # Map to standard names
                if "train_l2" in result:
                    result["train_loss"] = result["train_l2"]
                if "val_l2" in result:
                    result["val_loss"] = result["val_l2"]
                if "train_mse" in result:
                    result["train_loss"] = result["train_mse"]
                if "val_mse" in result:
                    result["val_loss"] = result["val_mse"]
                user_cb(result)
        callback.order = 50
        return callback

    def fit(
        self,
        train_df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str = "target",
        era_col: str = "era",
        epoch_callback: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Train LightGBM with era-aware train/val split."""
        self._feature_names = feature_cols

        # Era-aware split: last 20% of eras for validation
        eras = sorted(train_df[era_col].unique())
        split_idx = int(len(eras) * 0.8)
        train_eras = set(eras[:split_idx])
        val_eras = set(eras[split_idx:])

        train_mask = train_df[era_col].isin(train_eras)
        val_mask = train_df[era_col].isin(val_eras)

        X_train = train_df.loc[train_mask, feature_cols]
        y_train = train_df.loc[train_mask, target_col]
        X_val = train_df.loc[val_mask, feature_cols]
        y_val = train_df.loc[val_mask, target_col]

        dtrain = lgb.Dataset(X_train, label=y_train)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

        callbacks = [
            lgb.early_stopping(self.early_stopping_rounds),
            lgb.log_evaluation(100),
        ]

        if epoch_callback:
            callbacks.append(self._make_epoch_callback(epoch_callback, every_n=100))

        self._model = lgb.train(
            self.params,
            dtrain,
            num_boost_round=self.n_estimators,
            valid_sets=[dtrain, dval],
            valid_names=["train", "val"],
            callbacks=callbacks,
        )

        return {
            "best_iteration": self._model.best_iteration,
            "best_score": self._model.best_score,
            "train_eras": len(train_eras),
            "val_eras": len(val_eras),
        }

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
        """Generate predictions."""
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")

        preds = self._model.predict(df[feature_cols])
        return pd.Series(preds, index=df.index, name="prediction")

    def save(self, path: Path) -> None:
        """Save model and metadata."""
        if self._model is None:
            raise RuntimeError("No model to save")

        path.mkdir(parents=True, exist_ok=True)
        self._model.save_model(str(path / "model.txt"))

        meta = {
            "model_type": self.model_type,
            "params": self.params,
            "n_estimators": self.n_estimators,
            "feature_names": self._feature_names,
            "best_iteration": self._model.best_iteration,
        }
        with open(path / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    def load(self, path: Path) -> None:
        """Load model from disk."""
        self._model = lgb.Booster(model_file=str(path / "model.txt"))

        meta_path = path / "meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            self._feature_names = meta.get("feature_names", [])
            self.params = meta.get("params", self.params)
            self.n_estimators = meta.get("n_estimators", self.n_estimators)

    @property
    def model_type(self) -> str:
        return "lgbm"
