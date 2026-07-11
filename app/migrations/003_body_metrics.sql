-- Body metrics: long/narrow time series (Renpho now; Oura slots in later
-- with new source/metric values and zero schema change).

CREATE TABLE IF NOT EXISTS body_metrics (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,        -- 'renpho' | 'renpho_csv' | 'manual' | 'oura' (future)
    metric      TEXT NOT NULL,        -- 'weight_kg', 'body_fat_pct', 'muscle_mass_kg', ...
    value       DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL, -- device measurement time, not import time
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, metric, recorded_at)  -- makes sync/import idempotent
);
CREATE INDEX IF NOT EXISTS idx_body_metrics_series ON body_metrics(metric, recorded_at);

CREATE TABLE IF NOT EXISTS sync_state (
    source         TEXT PRIMARY KEY,  -- 'renpho', later 'oura'
    last_synced_at TIMESTAMPTZ,
    last_status    TEXT,
    cursor         JSONB
);
