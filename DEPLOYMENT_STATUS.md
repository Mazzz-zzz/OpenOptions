# OpenOptions — Deployment Status

**Last Updated:** 2026-03-05
**Status:** MVP deployed and operational (v3 — gamma/theta, DTE, spread, vol surface overhaul)

---

## Live URLs

| Service | URL |
|---|---|
| **Frontend** | https://main.deszj9mm9xrzu.amplifyapp.com/ |
| **API** | https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod |
| **Health Check** | https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod/health |

---

## AWS Infrastructure

All resources deployed in **ap-southeast-2 (Sydney)**.

### Backend — Lambda + API Gateway (SAM)

| Resource | Details |
|---|---|
| **CloudFormation Stack** | `openoptions` |
| **Lambda Function** | `openoptions-ApiFunction-0cbkTG57ErxE` |
| **Lambda Runtime** | Python 3.9, 512MB memory, 120s timeout |
| **API Gateway** | REST API `7ia5onp99c`, stage `prod` |
| **SAM S3 Bucket** | `aws-sam-cli-managed-default-samclisourcebucket-*` (auto-managed) |

**Environment variables** configured via SAM parameters:
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `DERIBIT_CLIENT_ID`, `DERIBIT_CLIENT_SECRET`
- `FRED_API_KEY`, `TRADIER_TOKEN`
- `VOL_THRESHOLD` (default 2.0 vol points)
- `CORS_ORIGINS` (default `*`)

### Database — RDS PostgreSQL

| Resource | Details |
|---|---|
| **Instance** | `openoptions-db.cl6a6mm8a6wq.ap-southeast-2.rds.amazonaws.com` |
| **Engine** | PostgreSQL 16 |
| **Instance Class** | db.t4g.micro (free tier eligible) |
| **Database Name** | `openoptions` |
| **User** | `postgres` |
| **Port** | 5432 |
| **Storage** | 20GB gp2 |
| **Public Access** | Yes (security group restricted) |

**Tables:**
```sql
contracts  — option contracts (symbol, underlying, strike, expiry, type, watchlist)
snapshots  — market data snapshots (bid, ask, mid, IVs, all greeks, deviation, net_edge)
alerts     — mispricing alerts (signal_type, confidence, dismissed)
```

**Columns added post-initial deploy:**
- `alerts.confidence` — VARCHAR(10), stores high/medium/low
- `snapshots.gamma` — NUMERIC(18,6), BS gamma
- `snapshots.theta` — NUMERIC(18,6), BS theta ($/day)

### Frontend — AWS Amplify

| Resource | Details |
|---|---|
| **App ID** | `deszj9mm9xrzu` |
| **Branch** | `main` |
| **Framework** | SvelteKit 5 (static adapter) |
| **Build Output** | `frontend/build/` |
| **Deploy Method** | Manual zip upload via `create-deployment` + presigned S3 URL |
| **Current Deployment** | Job #7 (SUCCEED) |

**Build-time env var:**
- `VITE_API_URL=https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod` — baked into JS bundle at build time

---

## Deployment History

| Version | Date | Changes |
|---|---|---|
| v1 | 2026-03-05 | Initial deploy — fetch pipeline, alert table, vol surface |
| v1.1 | 2026-03-05 | Fixed net_edge formula (was mixing vol decimals with price dollars) |
| v2 | 2026-03-05 | Sortable/filterable tables, confidence badges, tooltips on everything |
| v3 | 2026-03-05 | Gamma/theta greeks, DTE column, bid-ask spread column, vol surface overhaul (interpolation, moneyness, C/P split, 2D smile view, scatter overlay) |

---

## Redeployment Commands

### Backend (SAM)

```bash
cd backend

# Build
sam build

# Deploy
sam deploy --stack-name openoptions \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --parameter-overrides \
    DBHost=openoptions-db.cl6a6mm8a6wq.ap-southeast-2.rds.amazonaws.com \
    DBPassword=OpenOpts2026db
```

Notes:
- `--resolve-s3` auto-creates/uses a managed S3 bucket for artifacts
- `--capabilities CAPABILITY_IAM` required for Lambda execution role
- Deribit credentials, FRED key, and other params use defaults from `template.yaml` or previous deploy values
- Deployment takes ~2-3 minutes

### Frontend (Amplify)

```bash
cd frontend

# Build with API URL baked in
VITE_API_URL=https://7ia5onp99c.execute-api.ap-southeast-2.amazonaws.com/prod npm run build

# Zip from INSIDE the build directory (critical — chunk hashes change per build)
cd build
zip -r /tmp/frontend-build.zip .

# Create deployment and get presigned upload URL
aws amplify create-deployment --app-id deszj9mm9xrzu --branch-name main
# Returns: { "jobId": "N", "zipUploadUrl": "https://..." }

# Upload the zip
curl -T /tmp/frontend-build.zip "<zipUploadUrl>"

# Start deployment
aws amplify start-deployment --app-id deszj9mm9xrzu --branch-name main --job-id <N>

# Verify (takes ~10-15 seconds)
aws amplify get-job --app-id deszj9mm9xrzu --branch-name main --job-id <N> \
  --query 'job.summary.status' --output text
```

**Important:** Always zip from inside `build/`, not from the parent directory. Chunk hashes change on every rebuild, so old zips will cause 404s on JS assets.

### Database Migrations

```bash
# Connect to RDS
PGPASSWORD=OpenOpts2026db psql \
  -h openoptions-db.cl6a6mm8a6wq.ap-southeast-2.rds.amazonaws.com \
  -U postgres -d openoptions

# Run migration SQL
\i migrations/001_initial.sql

# Or run ad-hoc ALTER TABLEs:
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS gamma NUMERIC(18,6);
ALTER TABLE snapshots ADD COLUMN IF NOT EXISTS theta NUMERIC(18,6);
```

---

## Live API Test Results (v3)

| Endpoint | Result |
|---|---|
| `POST /api/fetch/BTC` | 986 snapshots, **75 alerts**, 12/12 expiries fitted |
| `POST /api/fetch/ETH` | ~800 snapshots, ~25 alerts, 12 expiries fitted |
| `POST /api/fetch/INVALID` | 400: "Unsupported underlying" |
| `POST /api/fetch/SPY` | 503: "Tradier API key not configured" |
| `GET /api/alerts?limit=2` | Returns gamma, theta, vega, spread data |
| `GET /api/surface/BTC?option_type=C` | 435 points, moneyness 0.54-1.97, spot $73,500, interpolated |
| `GET /api/contracts?watchlisted=true` | Filtered correctly |
| `GET /api/snapshots/{id}?limit=50` | Returns full greek history |

---

## Issues Fixed (All Versions)

1. **net_edge dimensional mismatch (v1.1, CRITICAL)** — Was `abs(deviation) - half_spread` (mixing vol ~0.05 with price ~$2). Fixed to `abs(deviation) * 100 * vega - half_spread` (all USD).
2. **Missing fields in API responses** — Surface/snapshots now return vega, delta, bid, ask, gamma, theta.
3. **Confidence not stored** — Added `confidence` column to alerts table.
4. **Alerts pagination bug** — Was ordering by net_edge but filtering by ID cursor. Fixed to order by ID desc.
5. **No input validation on fetch** — Added allowlist of supported underlyings, Tradier key check.
6. **FRED API crash** — Falls back to 5% rate if FRED is down.
7. **Null truthiness bug** — `if snap.market_iv` treats 0 as None. Fixed to `is not None`.
8. **NUMERIC(10,6) overflow** — Widened to NUMERIC(18,6) for BTC option values.
9. **Amplify 404 on JS chunks** — Must zip from inside `build/` directory, not parent.
10. **Vol surface 65% null gaps** — Added linear interpolation, moneyness filtering, C/P split.
11. **No moneyness normalization** — Added spot estimation and K/S axis.
12. **Frontend not re-rendering on data change** — Switched from `onMount` to reactive `$effect`.

---

## Not Yet Deployed

- **Tradier integration** — No API key configured (US equities)
- **Authentication** — No Cognito/auth layer
- **Scheduled fetches** — User-triggered only (EventBridge cron planned)
- **Data retention** — No auto-pruning of old snapshots
- **CloudWatch alarms** — No monitoring/alerting on errors
- **Open Interest / Volume** — Deribit provides these, not yet stored
- **Contract detail page** — Snapshot history endpoint exists, no UI yet
- **CSV export** — Not yet implemented
