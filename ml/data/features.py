"""Feature engineering for Numerai tournament data.

Computes era-level statistics, rolling windows, and group aggregates
on top of raw Numerai features.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def add_era_stats(df: pd.DataFrame, feature_cols: List[str], era_col: str = "era") -> pd.DataFrame:
    """Add per-era mean and std for each feature group."""
    era_means = df.groupby(era_col)[feature_cols].transform("mean")
    era_stds = df.groupby(era_col)[feature_cols].transform("std")

    for col in feature_cols:
        df[f"{col}_era_demean"] = df[col] - era_means[col]
        std = era_stds[col].replace(0, 1)
        df[f"{col}_era_zscore"] = (df[col] - era_means[col]) / std

    return df


def add_rolling_features(
    df: pd.DataFrame,
    feature_cols: List[str],
    era_col: str = "era",
    windows: Optional[List[int]] = None,
) -> pd.DataFrame:
    """Add rolling mean/std over eras for selected features.

    Eras must be sortable (numeric or lexicographic).
    """
    if windows is None:
        windows = [5, 10, 20]

    era_medians = df.groupby(era_col)[feature_cols].median().sort_index()

    for window in windows:
        rolling_mean = era_medians.rolling(window, min_periods=1).mean()
        rolling_std = era_medians.rolling(window, min_periods=1).std().fillna(0)

        mean_map = rolling_mean.to_dict(orient="index")
        std_map = rolling_std.to_dict(orient="index")

        for col in feature_cols:
            df[f"{col}_roll{window}_mean"] = df[era_col].map(
                lambda e, c=col: mean_map.get(e, {}).get(c, np.nan)
            )
            df[f"{col}_roll{window}_std"] = df[era_col].map(
                lambda e, c=col: std_map.get(e, {}).get(c, np.nan)
            )

    return df


def add_group_aggregates(
    df: pd.DataFrame,
    feature_groups: Dict[str, List[str]],
) -> pd.DataFrame:
    """Add mean/std across feature groups (cross-feature aggregation)."""
    for group_name, cols in feature_groups.items():
        valid_cols = [c for c in cols if c in df.columns]
        if not valid_cols:
            continue
        df[f"group_{group_name}_mean"] = df[valid_cols].mean(axis=1)
        df[f"group_{group_name}_std"] = df[valid_cols].std(axis=1)
        df[f"group_{group_name}_skew"] = df[valid_cols].skew(axis=1)

    return df


def get_feature_columns(df: pd.DataFrame, prefix: str = "feature_") -> List[str]:
    """Extract feature column names from a DataFrame."""
    return [c for c in df.columns if c.startswith(prefix)]


def neutralize_features(
    df: pd.DataFrame,
    prediction_col: str,
    neutralizers: List[str],
    proportion: float = 1.0,
) -> pd.Series:
    """Neutralize predictions against specified features.

    This reduces feature exposure at the cost of some correlation.
    """
    predictions = df[prediction_col].values
    exposures = df[neutralizers].values

    # OLS: predictions = exposures @ beta + residuals
    exposures_with_const = np.column_stack([exposures, np.ones(len(exposures))])
    beta, _, _, _ = np.linalg.lstsq(exposures_with_const, predictions, rcond=None)
    adjusted = predictions - proportion * (exposures_with_const @ beta - beta[-1])

    return pd.Series(adjusted, index=df.index, name=prediction_col)
