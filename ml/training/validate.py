"""Numerai-specific validation metrics.

Computes per-era correlation, Sharpe ratio, max drawdown,
and feature exposure — the metrics Numerai uses for scoring.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats


def per_era_correlation(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
) -> pd.Series:
    """Compute Spearman correlation per era."""
    def _corr(group):
        if len(group) < 5:
            return np.nan
        corr, _ = stats.spearmanr(group[prediction_col], group[target_col])
        return corr

    return df.groupby(era_col).apply(_corr)


def mean_correlation(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
) -> float:
    """Mean of per-era Spearman correlations."""
    era_corrs = per_era_correlation(df, prediction_col, target_col, era_col)
    return float(era_corrs.mean())


def sharpe_ratio(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
) -> float:
    """Sharpe ratio of per-era correlations (annualized, ~52 eras/year)."""
    era_corrs = per_era_correlation(df, prediction_col, target_col, era_col)
    if era_corrs.std() == 0:
        return 0.0
    return float(era_corrs.mean() / era_corrs.std())


def max_drawdown(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
) -> float:
    """Maximum drawdown of cumulative per-era correlation."""
    era_corrs = per_era_correlation(df, prediction_col, target_col, era_col)
    cumulative = era_corrs.cumsum()
    running_max = cumulative.cummax()
    drawdowns = cumulative - running_max
    return float(drawdowns.min())


def feature_exposure(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    feature_cols: Optional[List[str]] = None,
    era_col: str = "era",
) -> float:
    """Max per-era feature exposure (correlation of predictions with features).

    Lower is better — high exposure means the model is just betting on
    a single feature rather than finding alpha.
    """
    if feature_cols is None:
        feature_cols = [c for c in df.columns if c.startswith("feature_")]

    if not feature_cols:
        return 0.0

    max_exposures = []
    for era, group in df.groupby(era_col):
        if len(group) < 5:
            continue
        preds = group[prediction_col].values
        exposures = []
        for col in feature_cols:
            corr, _ = stats.spearmanr(preds, group[col].values)
            exposures.append(abs(corr))
        max_exposures.append(max(exposures))

    return float(np.mean(max_exposures)) if max_exposures else 0.0


def compute_all_metrics(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
    feature_cols: Optional[List[str]] = None,
) -> dict:
    """Compute all Numerai validation metrics."""
    return {
        "correlation": mean_correlation(df, prediction_col, target_col, era_col),
        "sharpe": sharpe_ratio(df, prediction_col, target_col, era_col),
        "max_drawdown": max_drawdown(df, prediction_col, target_col, era_col),
        "feature_exposure": feature_exposure(df, prediction_col, feature_cols, era_col),
    }
