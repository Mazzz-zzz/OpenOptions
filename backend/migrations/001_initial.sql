-- OpenOptions initial schema
-- Run: psql -d openoptions -f 001_initial.sql

BEGIN;

-- contracts: static, seeded on first fetch per symbol
CREATE TABLE IF NOT EXISTS contracts (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(60) UNIQUE NOT NULL,
    underlying      VARCHAR(15) NOT NULL,
    market          VARCHAR(15) NOT NULL,
    source          VARCHAR(15) NOT NULL,
    strike          NUMERIC(18,4) NOT NULL,
    expiry          DATE NOT NULL,
    option_type     CHAR(1) NOT NULL,
    is_watchlisted  BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- snapshots: one row per fetch per contract
CREATE TABLE IF NOT EXISTS snapshots (
    id              BIGSERIAL PRIMARY KEY,
    contract_id     INT REFERENCES contracts ON DELETE CASCADE NOT NULL,
    ts              TIMESTAMPTZ DEFAULT NOW(),
    bid             NUMERIC(18,4),
    ask             NUMERIC(18,4),
    mid             NUMERIC(18,4),
    market_iv       NUMERIC(18,6),
    model_iv        NUMERIC(18,6),
    delta_market    NUMERIC(18,6),
    delta_model     NUMERIC(18,6),
    vega            NUMERIC(18,6),
    deviation       NUMERIC(18,6),
    net_edge        NUMERIC(18,6),
    triggered_by    VARCHAR(20)
);

-- alerts: thin pointer to actionable snapshots
CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_id     BIGINT REFERENCES snapshots ON DELETE CASCADE NOT NULL,
    signal_type     VARCHAR(30) NOT NULL,
    confidence      VARCHAR(10),
    dismissed       BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_snapshots_contract_ts ON snapshots (contract_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_snapshots_ts ON snapshots (ts DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_dismissed_created ON alerts (dismissed, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_contracts_underlying_watchlisted ON contracts (underlying, is_watchlisted);

COMMIT;
