# Models

## Model Architecture

### Base Class

All models implement the `NumeraiModel` abstract base class (`models/base.py`):

```python
class NumeraiModel(ABC):
    @abstractmethod
    def fit(self, df, feature_cols, target_col, era_col, **kwargs) -> dict
    @abstractmethod
    def predict(self, df, feature_cols) -> pd.Series
    @abstractmethod
    def save(self, path: Path)
    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> "NumeraiModel"
    @property
    @abstractmethod
    def model_type(self) -> str
```

### LightGBM (`models/lgbm_model.py`)

The primary model. Uses gradient-boosted decision trees for tabular prediction.

#### Parameters

| Parameter | Default | Description |
|---|---|---|
| `num_leaves` | 512 | Maximum leaves per tree. Higher = more complex trees |
| `max_depth` | 8 | Maximum tree depth. Prevents overly deep splits |
| `learning_rate` | 0.005 | Step size per boosting round. Low = more rounds needed |
| `n_estimators` | 10,000 | Maximum boosting rounds (early stopping typically fires sooner) |
| `feature_fraction` | 0.1 | Fraction of features sampled per tree (10%) |
| `bagging_fraction` | 0.5 | Fraction of rows sampled per tree (50%) |
| `early_stopping_rounds` | 200 | Stop if no improvement for N rounds |
| `objective` | `regression` | L2 (MSE) loss |
| `metric` | `l2` | Evaluation metric on validation set |
| `verbosity` | `-1` | Suppress LightGBM logs (we use our own callbacks) |

#### Training Process

```
1. Receive: train_df, feature_cols, target_col, era_col

2. Era-based split:
   - Get unique eras from train_df
   - Sort eras chronologically
   - First 80% of eras → training set
   - Last 20% of eras → validation set

3. Create LightGBM datasets:
   - lgb.Dataset(train_X, train_y)
   - lgb.Dataset(val_X, val_y)  # reference=train_dataset

4. Train with callbacks:
   - lgb.train(params, train_set, valid_sets=[train_set, val_set])
   - Early stopping callback (built-in)
   - Epoch reporting callback (custom, every 100 rounds)
   - Log evaluation callback (built-in)

5. Return training info:
   - best_iteration: round with best validation score
   - best_score: best validation L2 loss
```

#### Era-Based Split Rationale

Standard random train/val split would leak information because rows within the same era are correlated. Era-based splitting ensures the validation eras are entirely unseen during training, which better estimates out-of-sample performance.

```
Eras: [era_0001, era_0002, ..., era_0800, era_0801, ..., era_1000]
       |←——— Training (80%) ———→|  |←—— Validation (20%) ——→|
```

#### Epoch Callback

Every 100 boosting rounds, the custom callback reports:

```python
{
    "epoch": 500,
    "train_loss": 0.04949,     # train L2 (MSE)
    "val_loss": 0.04974,       # validation L2
    "train_l2": 0.04949,       # alias
    "val_l2": 0.04974,         # alias
}
```

The callback handles different metric name formats between LightGBM versions:
- Looks for `l2` or `mse` in evaluation results
- Maps both to standardized `train_loss`/`val_loss` keys

#### Prediction

```python
predictions = model.predict(df, feature_cols)
# Returns pd.Series with same index as df
```

Uses the model's `best_iteration` for prediction (not the final iteration).

#### Serialization

```python
model.save(Path("output/model_target"))
# Creates:
#   output/model_target/model.lgb       # LightGBM binary model
#   output/model_target/metadata.json   # Feature names, params, best_iteration

model = LightGBMModel.load(Path("output/model_target"))
```

### Ensemble (`models/ensemble.py`)

Utility functions for combining predictions from multiple models:

#### Rank Average

```python
ensemble = rank_average({"target": preds1, "target_alpha_20": preds2, ...})
```

1. Rank-normalize each model's predictions to [0, 1] using percentile ranks
2. Average the ranks across models
3. Result is a single prediction per row

This is the standard Numerai ensemble technique. Rank-averaging is robust because:
- Invariant to prediction scale (each model's predictions are normalized)
- Combines diverse signals without one model dominating
- Preserves rank ordering from each model

#### Weighted Blend

```python
ensemble = weighted_blend(
    {"target": preds1, "target_alpha_20": preds2},
    {"target": 0.6, "target_alpha_20": 0.4}
)
```

Like rank average, but with custom weights per model. Useful when some targets are known to be more predictive.

## Multi-Target Strategy

### Why 6 Targets?

Numerai provides multiple target variants that capture different aspects of stock returns:
- Different time horizons (forward-looking periods)
- Different return decompositions (factors, styles)
- Different risk adjustments

Training on multiple targets and ensembling produces:
- **More robust predictions** — reduces variance from any single noisy target
- **Better feature utilization** — different targets emphasize different features
- **Higher effective Sharpe** — diversification across targets

### Target Handling

```python
# Skip targets with >50% NaN
if train_df[target].isna().sum() > len(train_df) * 0.5:
    continue

# Drop NaN rows for this specific target
mask = train_df[target].notna()
train_subset = train_df[mask]
```

Different targets have different NaN patterns — some may be missing for certain eras. Each model trains only on rows where its specific target is available.

## Adding New Models

To add a new model type:

1. Create `models/new_model.py` implementing `NumeraiModel`
2. Implement `fit()`, `predict()`, `save()`, `load()`, `model_type`
3. Import in `training/trainer.py` and add a model selection branch
4. Add the model type to the `model_type` validation in `backend/app/routers/ml.py`

Example candidates for future models:
- **TabNet** — attention-based tabular model
- **Neural network** — MLP or transformer on tabular data
- **XGBoost** — alternative gradient boosting library
- **Linear model** — as a baseline/ensemble component
