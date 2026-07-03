-- Journal: timeline spine + typed satellites, and daily wellness check-ins.

CREATE TABLE IF NOT EXISTS journal_entries (
    id          SERIAL PRIMARY KEY,
    entry_date  DATE NOT NULL,
    entry_type  TEXT NOT NULL CHECK (entry_type IN ('climbing', 'workout', 'note')),
    title       TEXT,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date);

CREATE TABLE IF NOT EXISTS climbing_sessions (
    id               SERIAL PRIMARY KEY,
    journal_entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id) ON DELETE CASCADE,
    location_type    TEXT NOT NULL DEFAULT 'gym' CHECK (location_type IN ('gym', 'outdoor')),
    location         TEXT,
    discipline       TEXT NOT NULL DEFAULT 'boulder'
                     CHECK (discipline IN ('boulder', 'sport', 'trad', 'board', 'gym_rope')),
    duration_min     INTEGER,
    feel_rating      SMALLINT CHECK (feel_rating BETWEEN 1 AND 5),
    skin_rating      SMALLINT CHECK (skin_rating BETWEEN 1 AND 5),
    session_rpe      SMALLINT CHECK (session_rpe BETWEEN 1 AND 10)
);

-- Per-climb rows so volume-by-grade is queryable.
CREATE TABLE IF NOT EXISTS climbs (
    id                  SERIAL PRIMARY KEY,
    climbing_session_id INTEGER NOT NULL REFERENCES climbing_sessions(id) ON DELETE CASCADE,
    name                TEXT,
    grade               TEXT NOT NULL,          -- as entered: 'V5', '7a+'
    grade_system        TEXT NOT NULL DEFAULT 'v_scale',
    grade_rank          SMALLINT,               -- app-computed ordinal for sorting
    style               TEXT CHECK (style IN ('flash', 'onsight', 'redpoint', 'repeat', 'attempt')),
    attempts            SMALLINT DEFAULT 1,
    sent                BOOLEAN NOT NULL DEFAULT TRUE,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS workouts (
    id               SERIAL PRIMARY KEY,
    journal_entry_id INTEGER NOT NULL UNIQUE REFERENCES journal_entries(id) ON DELETE CASCADE,
    workout_type     TEXT NOT NULL CHECK (workout_type IN
                     ('lifting', 'cardio', 'antagonist', 'core', 'mobility', 'other')),
    duration_min     INTEGER,
    session_rpe      SMALLINT CHECK (session_rpe BETWEEN 1 AND 10),
    details          JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- One row per day, upsert on log_date.
CREATE TABLE IF NOT EXISTS wellness_logs (
    id            SERIAL PRIMARY KEY,
    log_date      DATE NOT NULL UNIQUE,
    sleep_hours   REAL,
    sleep_quality SMALLINT CHECK (sleep_quality BETWEEN 1 AND 5),
    soreness      SMALLINT CHECK (soreness BETWEEN 1 AND 5),
    fatigue       SMALLINT CHECK (fatigue BETWEEN 1 AND 5),
    motivation    SMALLINT CHECK (motivation BETWEEN 1 AND 5),
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
