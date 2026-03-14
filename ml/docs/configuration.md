# Configuration Reference

All ML settings are managed via Pydantic's `BaseSettings` in `config/settings.py`. Settings are loaded from environment variables with the `ML_` prefix, or from a `.env` file in the `ml/` directory.

## Environment Variables

### Credentials

| Variable | Default | Description |
|---|---|---|
| `ML_NUMERAI_PUBLIC_ID` | `""` | Numerai API public key (for upload only) |
| `ML_NUMERAI_SECRET_KEY` | `""` | Numerai API secret key (for upload only) |
| `ML_NUMERAI_MODEL_ID` | `""` | Numerai model slot ID (for upload) |

Data download does not require credentials — `numerapi` supports anonymous access to tournament data.

### S3 Storage

| Variable | Default | Description |
|---|---|---|
| `ML_S3_BUCKET` | `openoptions-ml` | S3 bucket for models, data, job artifacts |
| `ML_S3_PREFIX` | `numerai/` | Key prefix within bucket |

### LightGBM Training

| Variable | Default | Description |
|---|---|---|
| `ML_DEFAULT_MODEL_TYPE` | `lgbm` | Model type (only `lgbm` currently) |
| `ML_DEFAULT_NUM_ROUNDS` | `10000` | Maximum boosting rounds |
| `ML_DEFAULT_LEARNING_RATE` | `0.005` | Learning rate (eta) |
| `ML_DEFAULT_NUM_LEAVES` | `512` | Max leaves per tree |
| `ML_DEFAULT_MAX_DEPTH` | `8` | Max tree depth |
| `ML_DEFAULT_FEATURE_FRACTION` | `0.1` | Column subsampling per tree (10%) |
| `ML_DEFAULT_BAGGING_FRACTION` | `0.5` | Row subsampling per tree (50%) |
| `ML_EARLY_STOPPING_ROUNDS` | `200` | Stop after N rounds without improvement |

### Feature Set

| Variable | Default | Description |
|---|---|---|
| `ML_FEATURE_SET` | `medium` | Feature set: `small` (42), `medium` (705), `all` (2376) |

### Feature Engineering

| Variable | Default | Description |
|---|---|---|
| `ML_ENABLE_ERA_STATS` | `true` | Per-era demeaning and z-score normalization |
| `ML_ENABLE_GROUP_AGGREGATES` | `true` | Cross-feature group statistics (mean, std, skew) |
| `ML_ENABLE_ROLLING_FEATURES` | `false` | Rolling mean/std over era windows |
| `ML_ENABLE_GARCH` | `false` | GARCH(1,1) conditional volatility features |
| `ML_ERA_STATS_TOP_N` | `30` | Number of top-variance features for era stats |

### Multi-Target Training

| Variable | Default | Description |
|---|---|---|
| `ML_MULTI_TARGET_ENABLED` | `true` | Train on multiple target columns |
| `ML_TARGET_COLS` | `target,target_cyrusd_20,...` | Comma-separated target columns |

Default targets:
- `target` — primary
- `target_cyrusd_20` — Cyrus USD 20-day forward
- `target_alpha_20` — Alpha 20-day
- `target_bravo_20` — Bravo 20-day
- `target_caroline_20` — Caroline 20-day
- `target_delta_20` — Delta 20-day

### Feature Neutralization

| Variable | Default | Description |
|---|---|---|
| `ML_NEUTRALIZATION_PROPORTION` | `0.5` | Strength of neutralization (0=none, 1=full) |
| `ML_NEUTRALIZATION_TOP_N` | `50` | Number of features to neutralize against |

### Memory Management

| Variable | Default | Description |
|---|---|---|
| `ML_MAX_TRAIN_ERAS` | `0` | Subsample training to N eras (0 = all eras) |

Use this on machines with limited RAM. Setting `ML_MAX_TRAIN_ERAS=200` reduces memory usage significantly at the cost of training on less data.

### Column Identifiers

| Variable | Default | Description |
|---|---|---|
| `ML_ERA_COL` | `era` | Column name for era identifier |
| `ML_TARGET_COL` | `target` | Primary target column name |
| `ML_FEATURE_PREFIX` | `feature_` | Prefix identifying feature columns |

## .env File

Create `ml/.env` (this file is gitignored):

```bash
# Required for submission upload
ML_NUMERAI_PUBLIC_ID=your_public_id_here
ML_NUMERAI_SECRET_KEY=your_secret_key_here

# Optional: specify model slot
ML_NUMERAI_MODEL_ID=your_model_id

# Override defaults
ML_FEATURE_SET=small
ML_DEFAULT_NUM_ROUNDS=5000
ML_EARLY_STOPPING_ROUNDS=100
```

## Hyperparameter Overrides

When launching from the dashboard, hyperparameters can be overridden via the JSON textarea in the training config modal. These are passed as `hyperparams` in the `TrainRequest` and stored in `ml_runs.hyperparams_json`.

Example override:
```json
{
  "num_leaves": 256,
  "learning_rate": 0.01,
  "max_depth": 6,
  "feature_fraction": 0.2
}
```

Note: hyperparameter overrides from the dashboard are stored for tracking purposes but do not yet override the Pydantic settings at runtime. This is a planned enhancement.

## Feature Groups

Numerai v5 features belong to named groups. The group assignments are defined in `features.json` (downloaded from Numerai) and referenced in `config/feature_groups.yaml`.

Known groups:
- `intelligence`, `charisma`, `strength`, `dexterity`, `constitution`
- `wisdom`, `agility`, `serenity`, `sunshine`, `rain`, `midnight`

Group aggregates (mean/std/skew) are computed across features within each group, adding 3 columns per group.
