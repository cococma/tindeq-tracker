-- Tindeq Progressor tracking schema

CREATE TABLE IF NOT EXISTS sessions (
    id          SERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id           BIGSERIAL PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    force_kg     REAL NOT NULL,
    device_ts_us BIGINT
);

CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements(session_id);
CREATE INDEX IF NOT EXISTS idx_measurements_time    ON measurements(recorded_at);
