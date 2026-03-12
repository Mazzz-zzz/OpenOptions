"""Download Numerai tournament data via numerapi.

Stubbed — requires valid Numerai credentials to actually download.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from config.settings import get_ml_settings


DATA_DIR = Path(__file__).parent.parent / "data_cache"


def download_current_round(dest: Optional[Path] = None) -> Path:
    """Download the current Numerai tournament dataset.

    Returns path to the downloaded parquet file.
    """
    settings = get_ml_settings()
    dest = dest or DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)

    if not settings.numerai_public_id:
        raise RuntimeError(
            "Numerai credentials not configured. "
            "Set ML_NUMERAI_PUBLIC_ID and ML_NUMERAI_SECRET_KEY env vars."
        )

    import numerapi

    napi = numerapi.NumerAPI(
        public_id=settings.numerai_public_id,
        secret_key=settings.numerai_secret_key,
    )
    current_round = napi.get_current_round()
    train_path = dest / f"train_r{current_round}.parquet"
    val_path = dest / f"validation_r{current_round}.parquet"
    live_path = dest / f"live_r{current_round}.parquet"

    if not train_path.exists():
        napi.download_dataset("v5.0/train.parquet", str(train_path))
    if not val_path.exists():
        napi.download_dataset("v5.0/validation.parquet", str(val_path))
    if not live_path.exists():
        napi.download_dataset("v5.0/live.parquet", str(live_path))

    return dest


def load_train_data(path: Optional[Path] = None) -> pd.DataFrame:
    """Load training data from parquet."""
    data_dir = path or DATA_DIR
    files = sorted(data_dir.glob("train_r*.parquet"))
    if not files:
        raise FileNotFoundError(f"No training data found in {data_dir}")
    return pd.read_parquet(files[-1])


def load_validation_data(path: Optional[Path] = None) -> pd.DataFrame:
    """Load validation data from parquet."""
    data_dir = path or DATA_DIR
    files = sorted(data_dir.glob("validation_r*.parquet"))
    if not files:
        raise FileNotFoundError(f"No validation data found in {data_dir}")
    return pd.read_parquet(files[-1])
