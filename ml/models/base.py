"""Abstract base class for Numerai models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

import pandas as pd


class NumeraiModel(ABC):
    """Interface that all Numerai tournament models must implement."""

    @abstractmethod
    def fit(
        self,
        train_df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str = "target",
        era_col: str = "era",
    ) -> dict:
        """Train the model.

        Returns a dict of training metrics (e.g. best_iteration, train_loss).
        """

    @abstractmethod
    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
        """Generate predictions for the given features.

        Returns a Series of predictions aligned with df.index.
        """

    @abstractmethod
    def save(self, path: Path) -> None:
        """Serialize model to disk."""

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load model from disk."""

    @property
    @abstractmethod
    def model_type(self) -> str:
        """Return the model type identifier (e.g. 'lgbm')."""
