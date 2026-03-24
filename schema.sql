-- Tindeq Progressor tracking schema

CREATE TABLE IF NOT EXISTS sessions (
    id               SERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at         TIMESTAMPTZ,
    exercise_type    TEXT NOT NULL DEFAULT 'repeaters',
    grip_type        TEXT NOT NULL DEFAULT 'half_crimp',
    edge_depth_mm    INTEGER NOT NULL DEFAULT 20,
    target_weight_kg REAL NOT NULL DEFAULT 0,
    -- Repeaters only
    on_seconds       INTEGER,
    off_seconds      INTEGER,
    target_reps      INTEGER,
    target_sets      INTEGER,
    -- Max hang only
    target_duration_s INTEGER,
    -- Recruitment pull only
    target_pull_reps  INTEGER,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id           BIGSERIAL PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    force_kg     REAL NOT NULL,
    device_ts_us BIGINT
);

CREATE TABLE IF NOT EXISTS baseline_tests (
    id            SERIAL PRIMARY KEY,
    tested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    test_type     TEXT NOT NULL,  -- 'mvc' or 'rfd'
    grip_type     TEXT NOT NULL DEFAULT 'half_crimp',
    edge_depth_mm INTEGER NOT NULL DEFAULT 20,
    -- MVC
    peak_force_kg REAL,
    -- RFD
    rfd_kg_per_s  REAL,
    peak_force_rfd_kg REAL,       -- peak force during RFD test
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements(session_id);
CREATE INDEX IF NOT EXISTS idx_measurements_time    ON measurements(recorded_at);
CREATE INDEX IF NOT EXISTS idx_baseline_type_date   ON baseline_tests(test_type, tested_at);
