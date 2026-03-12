"""Shared fixtures for ML tests."""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_data() -> pd.DataFrame:
    """Create synthetic Numerai-like data for testing.

    50 eras, 100 rows each, 10 features, 1 target.
    """
    rng = np.random.RandomState(42)
    n_eras = 50
    rows_per_era = 100
    n_features = 10

    rows = []
    for era in range(n_eras):
        features = rng.randn(rows_per_era, n_features)
        # Target is weakly correlated with feature 0
        target = 0.5 + 0.1 * features[:, 0] + 0.05 * rng.randn(rows_per_era)
        target = np.clip(target, 0, 1)

        for i in range(rows_per_era):
            row = {"era": f"era_{era:04d}", "target": target[i]}
            for j in range(n_features):
                row[f"feature_{j}"] = features[i, j]
            rows.append(row)

    return pd.DataFrame(rows)


@pytest.fixture
def feature_cols() -> List[str]:
    return [f"feature_{i}" for i in range(10)]
