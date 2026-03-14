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


def meta_model_contribution(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    meta_model_col: str = "numerai_meta_model",
    target_col: str = "target",
    era_col: str = "era",
) -> float:
    """Compute MMC (Meta-Model Contribution) per era, then average.

    MMC measures how much your predictions contribute beyond the meta model.
    It orthogonalizes your predictions against the meta model, then correlates
    the residual with the target.
    """
    def _gaussianize(s):
        """Rank to Gaussian (percentile -> inverse normal CDF)."""
        ranked = stats.rankdata(s)
        return stats.norm.ppf(ranked / (len(ranked) + 1))

    def _mmc_era(group):
        if len(group) < 10:
            return np.nan
        preds = _gaussianize(group[prediction_col].values)
        mm = _gaussianize(group[meta_model_col].values)
        target = _gaussianize(group[target_col].values)

        # Orthogonalize predictions w.r.t. meta model
        dot = np.dot(preds, mm)
        mm_norm = np.dot(mm, mm)
        if mm_norm == 0:
            return np.nan
        preds_ortho = preds - mm * (dot / mm_norm)

        # Correlate orthogonal component with target
        return np.corrcoef(preds_ortho, target)[0, 1]

    era_mmcs = df.groupby(era_col).apply(_mmc_era)
    return float(era_mmcs.mean())


def benchmark_comparison(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    benchmark_cols: List[str] = None,
    target_col: str = "target",
    era_col: str = "era",
) -> Dict[str, Dict[str, float]]:
    """Compare our model against Numerai benchmark models.

    Returns a dict of {benchmark_name: {correlation, sharpe}} so we can
    see where we stand relative to Numerai's own models.
    """
    if not benchmark_cols:
        return {}

    results = {}
    for bm_col in benchmark_cols:
        if bm_col not in df.columns:
            continue
        bm_corr = mean_correlation(df, bm_col, target_col, era_col)
        bm_sharpe = sharpe_ratio(df, bm_col, target_col, era_col)
        results[bm_col] = {"correlation": bm_corr, "sharpe": bm_sharpe}

    return results


def compute_all_metrics(
    df: pd.DataFrame,
    prediction_col: str = "prediction",
    target_col: str = "target",
    era_col: str = "era",
    feature_cols: Optional[List[str]] = None,
    meta_model_col: Optional[str] = None,
    benchmark_cols: Optional[List[str]] = None,
) -> dict:
    """Compute all Numerai validation metrics."""
    metrics = {
        "correlation": mean_correlation(df, prediction_col, target_col, era_col),
        "sharpe": sharpe_ratio(df, prediction_col, target_col, era_col),
        "max_drawdown": max_drawdown(df, prediction_col, target_col, era_col),
        "feature_exposure": feature_exposure(df, prediction_col, feature_cols, era_col),
    }

    # MMC if meta model is available
    if meta_model_col and meta_model_col in df.columns:
        metrics["mmc"] = meta_model_contribution(
            df, prediction_col, meta_model_col, target_col, era_col,
        )

    # Benchmark comparison
    if benchmark_cols:
        metrics["vs_benchmarks"] = benchmark_comparison(
            df, prediction_col, benchmark_cols, target_col, era_col,
        )

    return metrics
