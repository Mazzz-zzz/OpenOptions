# Options Mispricing Tracker
## Full-Stack Implementation Plan — Senior Developer Reference

| | |
|---|---|
| **Stack** | SvelteKit + FastAPI + PostgreSQL + AWS Amplify |
| **Markets** | Crypto (Deribit) + US Equities (Tradier/yfinance) |
| **Data Strategy** | On-demand only — collect when user explicitly requests |
| **Signals** | Vol surface irregularities + Greeks mispricing (delta/vega) |
| **Budget** | Near-zero — free tier AWS, free data sources where possible |
| **Version** | 1.0 — March 2026 |

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Database Schema](#2-database-schema)
3. [Backend — FastAPI on AWS Lambda](#3-backend--fastapi-on-aws-lambda)
4. [AWS Architecture](#4-aws-architecture)
5. [Frontend — SvelteKit](#5-frontend--sveltekit)
6. [Build Plan](#6-build-plan)
7. [Environment + Secrets](#7-environment--secrets)
8. [Gotchas and Known Issues](#8-gotchas-and-known-issues)

---

## 1. System Architecture

### 1.1 High-Level Overview

Three distinct layers: a SvelteKit frontend hosted on AWS Amplify, a FastAPI backend running on AWS Lambda via API Gateway, and a PostgreSQL database on AWS RDS free tier. Data collection is strictly demand-driven — no background polling unless the user explicitly triggers it.

| Layer | Choice |
|---|---|
| Frontend | SvelteKit on AWS Amplify — static build + SSR |
| API Layer | FastAPI on AWS Lambda via API Gateway |
| Database | PostgreSQL 16 on AWS RDS (db.t3.micro free tier) |
| Scheduled Jobs | AWS EventBridge + Lambda — lightweight, pay-per-use |
| Cache | In-memory Python dict on Lambda (no Redis needed v1) |
| Auth | AWS Cognito (Amplify built-in) |
| Secrets | AWS Secrets Manager for API keys |
| Monitoring | AWS CloudWatch — Lambda logs + custom metrics |

### 1.2 Data Flow

The key architectural decision: data is never automatically collected. Every snapshot is either user-triggered (button press) or runs on a conservative EventBridge schedule only for instruments the user has explicitly watchlisted.

```
User clicks 'Fetch' on frontend
        |
        v
SvelteKit  -->  POST /api/fetch/{symbol}  -->  FastAPI Lambda
                                                    |
                        +---------------------------+
                        |
               Deribit / Tradier API
                        |
               SVI surface fit  +  BS Greeks
                        |
               Write snapshots + alerts  -->  RDS Postgres
                        |
               Return results to frontend  -->  Update UI
```

> **Note:** EventBridge scheduled runs only fire for symbols in the user watchlist, at most every 15 minutes during market hours. Outside market hours, all schedules are suspended.

---

## 2. Database Schema

### 2.1 Three Tables

Keep it flat. Alerts point to snapshots; snapshots point to contracts. No time-series extension needed at this scale.

```sql
-- contracts: static, seeded on first fetch per symbol
contracts (
  id              SERIAL PRIMARY KEY,
  symbol          VARCHAR(60) UNIQUE,   -- 'BTC-27JUN25-100000-C'
  underlying      VARCHAR(15),          -- 'BTC', 'SPY', 'ETH'
  market          VARCHAR(15),          -- 'crypto', 'equity'
  source          VARCHAR(15),          -- 'deribit', 'tradier'
  strike          NUMERIC(18,4),
  expiry          DATE,
  option_type     CHAR(1),              -- 'C' or 'P'
  is_watchlisted  BOOLEAN DEFAULT false, -- drives EventBridge scheduling
  created_at      TIMESTAMPTZ DEFAULT NOW()
)

-- snapshots: one row per fetch per contract
snapshots (
  id              BIGSERIAL PRIMARY KEY,
  contract_id     INT REFERENCES contracts ON DELETE CASCADE,
  ts              TIMESTAMPTZ DEFAULT NOW(),
  bid             NUMERIC(18,4),
  ask             NUMERIC(18,4),
  mid             NUMERIC(18,4),
  market_iv       NUMERIC(10,6),
  model_iv        NUMERIC(10,6),        -- SVI-fitted
  delta_market    NUMERIC(10,6),
  delta_model     NUMERIC(10,6),        -- from BS + model_iv
  vega            NUMERIC(10,6),
  deviation       NUMERIC(10,6),        -- market_iv - model_iv
  net_edge        NUMERIC(10,6),        -- deviation - half_spread
  triggered_by    VARCHAR(20)           -- 'user' or 'schedule'
)

-- alerts: thin pointer to actionable snapshots
alerts (
  id              BIGSERIAL PRIMARY KEY,
  snapshot_id     BIGINT REFERENCES snapshots ON DELETE CASCADE,
  signal_type     VARCHAR(30),          -- 'surface_outlier', 'greek_divergence'
  dismissed       BOOLEAN DEFAULT false,
  created_at      TIMESTAMPTZ DEFAULT NOW()
)
```

### 2.2 Indexes

Minimum indexes for the dominant query patterns. Add more only when `EXPLAIN ANALYZE` shows a need.

```sql
CREATE INDEX ON snapshots (contract_id, ts DESC);
CREATE INDEX ON snapshots (ts DESC);
CREATE INDEX ON alerts (dismissed, created_at DESC);
CREATE INDEX ON contracts (underlying, is_watchlisted);
```

### 2.3 Retention Policy

Use pg_cron (available on RDS) to trim snapshots older than 30 days. Alerts are kept indefinitely — they are low volume.

```sql
SELECT cron.schedule('0 2 * * *',
  $$ DELETE FROM snapshots WHERE ts < NOW() - INTERVAL '30 days' $$);
```

### 2.4 Key Alert Query

Alerts contain no data themselves — they point to a snapshot. The full frontend query is just:

```sql
SELECT s.*, c.symbol, c.strike, c.expiry
FROM alerts a
JOIN snapshots s ON s.id = a.snapshot_id
JOIN contracts c ON c.id = s.contract_id
WHERE a.dismissed = false
ORDER BY s.net_edge DESC;
```

---

## 3. Backend — FastAPI on AWS Lambda

### 3.1 Project Structure

```
backend/
  app/
    main.py              # FastAPI app entrypoint
    routers/
      fetch.py           # POST /fetch/{symbol}  — user-triggered
      alerts.py          # GET  /alerts          — paginated
      contracts.py       # GET/POST /contracts   — watchlist mgmt
      surface.py         # GET  /surface/{underlying}
    services/
      deribit.py         # Deribit REST client
      tradier.py         # Tradier REST client
      pricing.py         # Black-Scholes + SVI surface fit
      detector.py        # Mispricing signal logic
    models.py            # SQLAlchemy ORM models
    database.py          # Connection pool + session factory
    config.py            # Settings from Secrets Manager
  handler.py             # Mangum wrapper for Lambda
  requirements.txt
  template.yaml          # AWS SAM template
```

### 3.2 Lambda Deployment with SAM

Use AWS SAM rather than raw CloudFormation. Mangum wraps FastAPI for Lambda/API Gateway compatibility.

```python
# handler.py
from mangum import Mangum
from app.main import app
handler = Mangum(app, lifespan='off')
```

```bash
# Deploy
sam build && sam deploy --guided
```

> **Note:** Lambda cold starts with FastAPI + scipy can be 3–5 seconds. Use a container image (up to 10GB, eliminates packaging problems) or provision a single warm instance. Alternatively keep SVI fitting as a separate async Lambda.

### 3.3 API Endpoints

| Method + Path | Description | Notes |
|---|---|---|
| `POST /fetch/{symbol}` | Trigger data collection for one underlying (BTC, SPY) | User-triggered only. Fetches full chain, runs SVI fit, writes snapshots + alerts. |
| `GET /alerts` | Paginated alert list | Cursor-based. Query params: `cursor`, `limit` (default 50), `signal_type` filter. |
| `GET /surface/{underlying}` | Latest vol surface data points | Returns moneyness + market_iv + model_iv per expiry slice for 3D chart. |
| `GET /contracts` | List watchlisted contracts | Filter by underlying, market, active/inactive. |
| `POST /contracts/{id}/watch` | Add contract to watchlist | Sets `is_watchlisted=true` — enables EventBridge schedule. |
| `DELETE /contracts/{id}/watch` | Remove from watchlist | Disables scheduled collection for that contract. |
| `GET /snapshots/{contract_id}` | History for one contract | Returns last N snapshots for sparkline chart. |
| `POST /alerts/{id}/dismiss` | Dismiss a specific alert | Sets `dismissed=true`. |

### 3.4 Data Collection Logic

The fetch endpoint runs the full pipeline synchronously and returns results within the same HTTP response.

```python
# routers/fetch.py
@router.post('/fetch/{underlying}')
async def fetch_chain(underlying: str, db: Session = Depends(get_db)):
    # 1. Determine source
    source = 'deribit' if underlying in CRYPTO else 'tradier'
    chain = await get_client(source).fetch_chain(underlying)

    # 2. Upsert contracts
    contract_ids = upsert_contracts(db, chain)

    # 3. Fit SVI surface per expiry (one fit per slice)
    surface = fit_svi_by_expiry(chain)

    # 4. Compute greeks + mispricing per contract
    snapshots = []
    for c in chain:
        model_iv = surface[c.expiry].predict(c.moneyness)
        deviation = c.market_iv - model_iv
        spread = c.ask - c.bid
        net_edge = abs(deviation) - (spread / 2)
        snap = Snapshot(..., triggered_by='user')
        snapshots.append(snap)

        # 5. Write alert if mispricing survives spread
        if abs(deviation) > VOL_THRESHOLD and net_edge > 0:
            db.add(Alert(snapshot=snap, signal_type=classify(deviation, c)))

    db.bulk_save(snapshots)
    db.commit()
    return {'snapshots': len(snapshots), 'alerts_raised': ...}
```

### 3.5 Pricing Engine

| Component | Detail |
|---|---|
| Library | `py_vollib` — wraps QuantLib BS implementation. `pip install py_vollib`. |
| SVI Fitting | `scipy.optimize.curve_fit` with SVI parametrization. Fit per expiry slice. |
| Risk-free rate | Fetch daily from FRED API (series `DGS1MO`). Cache in Lambda env var. |
| Moneyness | Use `log(K/F)` where F is the forward price. More stable than K/S for fitting. |
| Outlier threshold | 2.0 vol points default. Make this a configurable env variable (`VOL_THRESHOLD`). |
| Early exercise | Deribit is European-style — BS is exact. For equity (American), add ~5% premium heuristic or use binomial tree via QuantLib. |

---

## 4. AWS Architecture

### 4.1 Services Used

| Service | Purpose | Tier / Cost | Notes |
|---|---|---|---|
| AWS Amplify | SvelteKit frontend hosting + CI/CD | Free tier: 1000 build mins/mo | Connect GitHub repo; auto-deploy on push to main |
| API Gateway | HTTP API fronting Lambda | Free tier: 1M requests/mo | Use HTTP API not REST API — cheaper and faster |
| Lambda | FastAPI backend | Free tier: 1M req/mo, 400K GB-s compute | Single function with Mangum adapter |
| RDS PostgreSQL | Primary database | Free tier: db.t3.micro, 20GB | Single-AZ, no Multi-AZ needed for v1 |
| Secrets Manager | API keys (Deribit, Tradier) | ~$0.40/secret/month | Rotate keys without redeploying Lambda |
| EventBridge | Scheduled data collection | Free tier: 14M events/mo | Fires Lambda for watchlisted symbols on schedule |
| CloudWatch | Logs + alerting | Free tier: 5GB logs/mo | Set alarm on Lambda error rate |
| Cognito | Authentication | Free tier: 50K MAU | Amplify handles login UI automatically |
| VPC (optional) | Secure RDS access | Free | Add in v2 — RDS public endpoint + security group is fine for v1 |

### 4.2 EventBridge Scheduled Collection

The schedule is intentionally conservative. EventBridge triggers a separate Lambda (not the API Lambda) to avoid interfering with user requests.

```yaml
# SAM template snippet
CollectionSchedule:
  Type: AWS::Events::Rule
  Properties:
    ScheduleExpression: 'cron(0/15 14-21 ? * MON-FRI *)'  # every 15min, market hours UTC
    Targets:
      - Arn: !GetAtt CollectionLambda.Arn
        Input: '{"source": "schedule"}'
```

The collection Lambda queries `contracts WHERE is_watchlisted = true` and runs the same fetch pipeline as the user-triggered endpoint. `triggered_by` is set to `'schedule'` so the frontend can distinguish.

### 4.3 AWS Amplify SvelteKit Setup

Amplify Gen 2 has native SvelteKit support. Use `adapter-static` for a fully static build — all data comes from API calls so SSR is not required. Set `prerender = false` on dynamic routes.

```yaml
# amplify.yml
version: 1
frontend:
  phases:
    preBuild:
      commands:
        - npm ci
    build:
      commands:
        - npm run build
  artifacts:
    baseDirectory: build
    files:
      - '**/*'
  cache:
    paths:
      - node_modules/**/*
```

Set `VITE_API_URL` as an Amplify environment variable pointing to your API Gateway endpoint. Amplify injects it at build time.

---

## 5. Frontend — SvelteKit

### 5.1 Project Structure

```
frontend/
  src/
    routes/
      +layout.svelte         # Nav, auth wrapper
      +page.svelte           # Dashboard: alert table + fetch controls
      surface/
        +page.svelte         # 3D vol surface chart
      contracts/
        +page.svelte         # Watchlist management
    lib/
      api.js                 # fetch() wrappers for all endpoints
      stores.js              # Svelte writable stores for alerts, surface
      components/
        AlertTable.svelte
        FetchButton.svelte   # Triggers POST /fetch/{symbol}
        VolSurface.svelte    # Plotly 3D chart
        ContractRow.svelte
        Pagination.svelte    # Cursor-based next page
  svelte.config.js
  vite.config.js
```

### 5.2 FetchButton Component

```svelte
<!-- FetchButton.svelte -->
<script>
  import { alerts } from '$lib/stores.js'
  export let symbol
  let loading = false
  let result = null

  async function fetchNow() {
    loading = true
    result = await api.post(`/fetch/${symbol}`)
    alerts.refresh()  // update alert store
    loading = false
  }
</script>

<button on:click={fetchNow} disabled={loading}>
  {loading ? 'Fetching...' : `Fetch ${symbol}`}
</button>

{#if result}
  <p>{result.alerts_raised} alerts raised from {result.snapshots} contracts</p>
{/if}
```

### 5.3 Cursor-Based Pagination Store

```javascript
// stores.js
export const alerts = (() => {
  const { subscribe, update } = writable({ items: [], cursor: null, hasMore: true })

  async function load(reset = false) {
    const state = get(alerts)
    const cursor = reset ? null : state.cursor
    const res = await api.get(`/alerts?cursor=${cursor ?? ''}`)
    update(s => ({
      items: reset ? res.data : [...s.items, ...res.data],
      cursor: res.next_cursor,
      hasMore: !!res.next_cursor
    }))
  }

  return { subscribe, load, refresh: () => load(true) }
})()
```

Corresponding FastAPI endpoint:

```python
@app.get("/alerts")
async def get_alerts(cursor: int = None, limit: int = 50):
    query = """
        SELECT a.id, s.*, c.symbol, c.strike, c.expiry
        FROM alerts a
        JOIN snapshots s ON s.id = a.snapshot_id
        JOIN contracts c ON c.id = s.contract_id
        WHERE a.dismissed = false
        AND (%(cursor)s IS NULL OR a.id < %(cursor)s)
        ORDER BY s.net_edge DESC
        LIMIT %(limit)s
    """
    rows = db.execute(query, {"cursor": cursor, "limit": limit + 1})
    has_more = len(rows) > limit
    return {
        "data": rows[:limit],
        "next_cursor": rows[-2].id if has_more else None
    }
```

### 5.4 Vol Surface Chart

```svelte
<script>
  import Plotly from 'plotly.js-dist'
  import { onMount } from 'svelte'
  export let surfaceData  // { x: moneyness[], y: expiry[], z: iv[][] }

  onMount(() => {
    Plotly.newPlot('surface', [{
      type: 'surface',
      x: surfaceData.x,
      y: surfaceData.y,
      z: surfaceData.z,
      colorscale: 'Viridis'
    }], {
      title: 'Vol Surface',
      scene: { camera: { eye: { x: 1.5, y: 1.5, z: 0.8 } } }
    })
  })
</script>

<div id="surface" style="width:100%; height:500px"></div>
```

---

## 6. Build Plan

### Phase 1 — Foundation (Days 1–2)

1. Set up AWS: create RDS instance, Lambda function, API Gateway HTTP API, Secrets Manager entries for Deribit + Tradier keys.
2. Run database migrations — create three tables + indexes.
3. Implement Deribit REST client in `services/deribit.py` — fetch BTC options chain.
4. Implement Black-Scholes greeks via `py_vollib` — validate against known values.
5. Implement SVI surface fitting via `scipy` — test on sample Deribit chain data.
6. Wire up `POST /fetch/BTC` end-to-end — no frontend yet, test with curl.
7. Deploy Lambda via SAM, confirm cold start < 10s.

### Phase 2 — Alerts + Frontend Shell (Days 3–4)

1. Implement mispricing detector — `surface_outlier` and `greek_divergence` signal classification.
2. Implement `GET /alerts` with cursor pagination.
3. Scaffold SvelteKit project, connect to Amplify, set `VITE_API_URL`.
4. Build `FetchButton` component — `POST /fetch/BTC` and show result count.
5. Build `AlertTable` component — display alerts with `net_edge`, `signal_type`, contract symbol.
6. Build `Pagination` component — load more button using cursor.
7. Confirm full flow: click fetch → alerts appear in table.

### Phase 3 — Vol Surface + Watchlist (Days 5–6)

1. Implement `GET /surface/BTC` — aggregate surface points for Plotly.
2. Build `VolSurface.svelte` — 3D chart with Plotly, market IV vs model IV.
3. Implement watchlist endpoints (`POST/DELETE /contracts/:id/watch`).
4. Build Contracts page — list contracts, toggle watchlist, show last fetched time.
5. Add Tradier client for US equity options (SPY, AAPL etc).
6. Add Cognito authentication via Amplify Auth.

### Phase 4 — Scheduled Collection + Polish (Week 2)

1. Create separate collection Lambda triggered by EventBridge.
2. Configure EventBridge schedule — every 15 minutes, market hours only.
3. Confirm `is_watchlisted` flag gates scheduled collection correctly.
4. Add CloudWatch alarms: Lambda error rate > 1%, RDS CPU > 80%.
5. Add dismiss button to alerts in frontend.
6. Add sparkline history chart on contract detail view.
7. Performance: add Lambda SnapStart or provisioned concurrency if cold start is painful.
8. Write README covering local dev setup, SAM deployment, Amplify setup.

---

## 7. Environment + Secrets

### 7.1 Lambda Environment Variables

| Variable | Value |
|---|---|
| `DB_HOST` | RDS endpoint hostname |
| `DB_NAME` | postgres |
| `DB_PORT` | 5432 |
| `DB_SECRET_ARN` | ARN of Secrets Manager secret containing DB credentials |
| `DERIBIT_SECRET_ARN` | ARN for Deribit API key pair |
| `TRADIER_SECRET_ARN` | ARN for Tradier token |
| `FRED_API_KEY` | Free FRED API key for risk-free rate (non-secret, fine in env var) |
| `VOL_THRESHOLD` | `2.0` — vol point deviation required to raise an alert |
| `MARKET_TZ` | `America/New_York` |
| `ENVIRONMENT` | `production` or `development` |

### 7.2 Amplify Environment Variables

Set in Amplify console under App Settings > Environment Variables.

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://{api-gateway-id}.execute-api.{region}.amazonaws.com` |
| `VITE_AWS_REGION` | `ap-southeast-2` (Sydney) |
| `VITE_USER_POOL_ID` | Cognito User Pool ID |
| `VITE_USER_POOL_CLIENT_ID` | Cognito App Client ID |

---

## 8. Gotchas and Known Issues

**Lambda + scipy cold start**
scipy alone is ~50MB. Use Lambda layers or a container image — container images up to 10GB are supported and eliminate packaging problems entirely.

**RDS in VPC**
If you put RDS in a VPC (recommended for v2), Lambda must also be in the VPC, which adds ~500ms to cold start. For v1, RDS public endpoint + security group IP allowlist is acceptable.

**Deribit rate limits**
Public API: 20 requests/second. The full BTC options chain is ~2000 contracts. Batch fetch by expiry rather than per-contract. Use `/public/get_book_summary_by_currency` to get all contracts in one call.

**Tradier delayed data**
Free tier is 15-minute delayed. Fine for model validation but label it clearly in the UI. Real-time requires the $10/mo Tradier Developer plan.

**SVI fit failures**
For short-dated, deep OTM options the SVI fit can fail or produce nonsensical results. Wrap `curve_fit` in try/except, skip contracts where fit RMSE > 0.05, and flag them as `unrated` rather than crashing the batch.

**EventBridge market hours**
cron expressions in EventBridge use UTC. US market hours are 14:30–21:00 UTC. Account for DST manually or add a Lambda guard that checks the current datetime before running.

**Amplify SSR vs static**
SvelteKit with `adapter-node` needs a Node.js server. For Amplify, use `adapter-static` for a fully static build — fine since all data comes from API calls. Set `prerender = false` on dynamic routes.

**CORS**
API Gateway and FastAPI both need CORS configured. Set `allow_origins` to your Amplify domain in FastAPI `CORSMiddleware` and mirror it in API Gateway CORS settings. Missing this on either side will silently block all requests.
