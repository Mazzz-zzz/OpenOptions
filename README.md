# OpenOptions — Options Mispricing Tracker + Numerai ML

Real-time options mispricing detection across crypto (Deribit) and US equities/futures (Tastytrade). Fits SVI volatility surfaces per expiry, computes Black-Scholes greeks, and flags contracts where market IV diverges from the fitted surface.

Also includes a Numerai tournament ML pipeline with multi-target LightGBM training, SageMaker integration, and a live training dashboard.

## Architecture

| Layer | Technology |
|---|---|
| Frontend | SvelteKit 5 (Svelte 5 runes, static adapter) on AWS Amplify |
| Backend | FastAPI on AWS Lambda (via Mangum + SAM) |
| Database | PostgreSQL 16 on AWS RDS (db.t4g.micro) |
| Data Sources | Deribit REST API (crypto), Tastytrade REST API (equities/futures) |
| ML Training | LightGBM on SageMaker, dashboard monitoring |
| Region | ap-southeast-2 (Sydney) |

## Live URLs

| Service | URL |
|---|---|
| Frontend | https://main.deszj9mm9xrzu.amplifyapp.com/ |
| API | https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod |
| Health | https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod/health |

## Project Structure

```
backend/
  app/
    main.py              # FastAPI app + CORS
    config.py            # Pydantic settings from env vars
    database.py          # SQLAlchemy session factory
    models.py            # ORM: contracts, snapshots, alerts
    routers/
      fetch.py           # POST /api/fetch/{underlying} — full pipeline
      alerts.py          # GET /api/alerts, POST dismiss
      contracts.py       # GET /api/contracts, watchlist toggle
      surface.py         # GET /api/surface/{underlying}, snapshots history
    services/
      deribit.py         # Deribit REST client
      tradier.py         # Tradier REST client
      pricing.py         # BS greeks (delta, vega, gamma, theta) + SVI surface fitting
      detector.py        # Mispricing signal classification
  handler.py             # Mangum Lambda handler
  template.yaml          # SAM deployment template
  migrations/            # SQL migration scripts
  tests/                 # pytest test suite

frontend/
  src/
    routes/
      +layout.svelte     # Nav bar (Dashboard, Vol Surface, Contracts, ML)
      +page.svelte       # Dashboard: fetch buttons + alert table
      contracts/         # Contract browser with watchlist, sorting, filtering
      surface/           # Vol surface with 3D/2D views, C/P toggle
      ml/                # ML dashboard: training, experiments, models, rounds
    lib/
      api.ts             # Typed API client + interfaces
      stores.ts          # Svelte stores (alerts, surface, contracts)
      ml-stores.ts       # ML stores (experiments, models, training triggers)
      components/
        AlertTable.svelte  # Sortable/filterable alert table with all greeks
        FetchButton.svelte # Trigger fetch with loading state
        VolSurface.svelte  # Plotly 3D surface + 2D IV smile
        ml/                # ML components (TrainConfigModal, TrainingProgress)

ml/                        # Numerai ML training pipeline (see ml/README.md)
  config/settings.py       # MlSettings (Pydantic, env prefix ML_)
  data/download.py         # numerapi data download + caching
  data/features.py         # Feature engineering (era stats, groups, neutralization)
  models/lgbm_model.py     # LightGBM with era-aware CV + epoch callbacks
  training/trainer.py      # Full pipeline (download → train → submit)
  sagemaker/launch_job.py  # Package code + launch SageMaker training job
  bootstrap.py             # SageMaker entry point
```

## How It Works

1. **User triggers fetch** via `POST /api/fetch/{underlying}` (e.g., BTC, ETH)
2. **Option chain fetched** from Deribit (crypto) or Tradier (equities)
3. **SVI surface fitted** per expiry using `scipy.optimize.curve_fit` on total implied variance
4. **Model IV** interpolated from fitted surface for each contract's log-moneyness
5. **Greeks computed** via Black-Scholes:
   - **Delta** — directional exposure (from both market IV and model IV)
   - **Vega** — sensitivity to 1% vol change (converts vol edge to dollar edge)
   - **Gamma** — rate of change of delta per $1 underlying move
   - **Theta** — daily time decay in dollars
6. **Mispricing detected** when:
   - `surface_outlier`: |market_iv - model_iv| > vol threshold (default 2%)
   - `greek_divergence`: |delta_market - delta_model| > 5 delta points
7. **Net edge** computed: `|deviation| * 100 * vega - half_spread` (all in USD)
8. **Alerts** created with confidence levels (high/medium/low) based on deviation ratio and edge-to-spread ratio

## Pricing Model

### Black-Scholes

Used for all greeks computation. Standard European option pricing with:
- `d1 = (ln(S/K) + (r + 0.5*sigma^2)*T) / (sigma*sqrt(T))`
- `d2 = d1 - sigma*sqrt(T)`
- Delta, Vega, Gamma, Theta derived from d1/d2 with `N(x)` and `N'(x)`
- Risk-free rate sourced live from FRED API (1-month Treasury), fallback 0.05

### SVI (Stochastic Volatility Inspired)

Used for the volatility surface model:
- `w(k) = a + b * (rho * (k-m) + sqrt((k-m)^2 + sigma^2))`
- where `k = ln(K/F)` is log-moneyness, `w` is total implied variance
- Fitted per expiry slice with no-arbitrage bounds on parameters
- RMSE threshold of 0.05 rejects poor fits

## Frontend Features

### Dashboard (`/`)
- **Fetch buttons** for BTC/ETH — triggers full pipeline, shows alert/contract count
- **Alert table** with 14 columns, all sortable:
  - Symbol, Strike, Expiry, **DTE** (days to expiry, color-coded), Type
  - Signal (Surface/Greek badge), Confidence (high/medium/low badge)
  - Market IV, Model IV, Deviation (vol points, green/red), **Spread** (bid-ask, red if wide)
  - **Net Edge** ($), **Gamma** (Γ), **Theta** (Θ $/day)
- Filters: search by symbol, underlying, signal type, confidence
- Tooltips on every column, badge, and control explaining the metric

### Volatility Surface (`/surface`)
- **Calls/Puts/Both toggle** — view option types separately or combined
- **3D Surface view** — Plotly surface with market IV (Viridis) and model IV (Cividis) overlaid
  - Scatter point overlay color-coded by deviation (<2% green, 2-5% orange, >5% red)
  - `connectgaps: true` for smooth rendering despite missing data
  - Rich hover: symbol, IV, model IV, deviation, net edge
- **2D IV Smile view** — per-expiry curves, solid = market, dotted = model
  - ATM vertical line at moneyness = 1.0
- **Moneyness toggle** — switch x-axis between absolute strike ($) and moneyness (K/S)
- **Spot price** estimated from ATM strike (minimum IV on nearest expiry)
- **Linear interpolation** fills interior null gaps along the strike axis
- **Moneyness filter** (0.5x-2.0x) removes extreme OTM noise

### Contracts (`/contracts`)
- Full contract browser with sorting (symbol, underlying, strike, expiry, DTE, type, watchlist)
- Inline watchlist toggle (★/☆)
- Filters: search, underlying, option type, watchlist status

### UX
- Dark theme (GitHub-inspired)
- Tooltips on every interactive element explaining what each metric means
- Svelte 5 runes (`$state`, `$derived.by`) for reactive client-side sorting/filtering
- All data loaded client-side for instant sort/filter (no round-trips)

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/fetch/{underlying}` | Fetch chain + fit surface + detect mispricings |
| GET | `/api/alerts` | List alerts (cursor pagination, filter by signal_type/underlying) |
| POST | `/api/alerts/{id}/dismiss` | Dismiss an alert |
| GET | `/api/contracts` | List contracts (filter by underlying, watchlisted, limit) |
| POST | `/api/contracts/{id}/watch` | Add to watchlist |
| DELETE | `/api/contracts/{id}/watch` | Remove from watchlist |
| GET | `/api/surface/{underlying}?option_type=C` | Vol surface data (with moneyness, interpolation, spot) |
| GET | `/api/snapshots/{contract_id}` | Snapshot history for a contract |

## Database Schema

```sql
contracts (id, symbol, underlying, market, source, strike, expiry, option_type, is_watchlisted)
snapshots (id, contract_id, ts, bid, ask, mid, market_iv, model_iv,
           delta_market, delta_model, vega, gamma, theta,
           deviation, net_edge, triggered_by)
alerts    (id, snapshot_id, signal_type, confidence, dismissed, created_at)
```

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ENVIRONMENT=development
export DB_HOST=localhost
export DB_NAME=openoptions
export DB_USER=postgres
export DB_PASSWORD=yourpassword
export DERIBIT_CLIENT_ID=your_id
export DERIBIT_CLIENT_SECRET=your_secret

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
```

### Tests

```bash
cd backend
python3 -m pytest -v
```

Test coverage:
- **test_pricing.py** (16) — BS price/delta/vega, put-call parity, SVI fitting
- **test_detector.py** (12) — Mispricing classification, confidence assessment
- **test_deribit.py** (7) — Instrument parsing, chain fetching with mocks
- **test_tradier.py** (5) — Expiration/chain parsing, edge cases
- **test_api.py** (20) — All endpoints: alerts CRUD + pagination, contracts + watchlist, snapshots, surface
- **test_fetch.py** (4) — Fetch pipeline integration
- **test_ml.py** (19) — ML endpoints: experiments, models, rounds, overview
- **ml/tests/** (27) — Feature engineering, LightGBM training, validation metrics, submission

## Deployment

See `DEPLOYMENT_STATUS.md` for full infrastructure details and redeployment commands.

## ML Pipeline (Numerai)

A complete training framework for the Numerai Classic tournament. See [`ml/README.md`](ml/README.md) for full details.

### Pipeline

1. **Download** Numerai v5 data via numerapi (anonymous, ~6GB)
2. **Feature engineering** — era stats (demeaning, z-score), group aggregates
3. **Multi-target training** — 6 LightGBM models (target + 5 variants)
4. **Ensemble** — rank-average across target models
5. **Neutralization** — OLS residualization against top 50 features
6. **Validation** — per-era correlation, Sharpe ratio, max drawdown, feature exposure
7. **Submission** — rank-normalized CSV, optional upload to Numerai

### SageMaker Integration

Training runs on SageMaker (ml.m5.xlarge, ~$0.40/run). The dashboard provides:
- **Start Training** button with experiment name, feature set, instance type selection
- **Live progress** — step-level progress bar and epoch-level loss charts
- **Experiment tracking** — compare runs across experiments

Architecture: SageMaker writes progress to S3 → Poller Lambda (1/min) syncs to RDS → API serves to dashboard (5s poll).

```bash
# Launch from CLI
cd ml && python3 sagemaker/launch_job.py --feature-set small

# Or from the dashboard at /ml tab → Start Training
```

### ML API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/ml/overview` | Dashboard summary (active runs, best model) |
| GET | `/api/ml/experiments` | List experiments with run counts |
| GET | `/api/ml/runs/{id}/metrics` | Epoch-level train/val loss data |
| POST | `/api/ml/train` | Start a SageMaker training job |
| POST | `/api/ml/runs/{id}/cancel` | Cancel a running job |

### ML Tests

```bash
cd ml && python3 -m pytest tests/ -v   # 27 tests
```

## Known Limitations

- **Local ML training needs ~16GB RAM** — use SageMaker for the full dataset
- **No scheduled fetching** — data collection is user-triggered only (no EventBridge/cron yet)
- **No authentication** — endpoints are publicly accessible
- **No OI/volume data** — Deribit provides these but we don't store them yet
- **Python 3.9** — Lambda runtime constraint; uses `from __future__ import annotations`
