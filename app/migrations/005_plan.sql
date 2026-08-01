-- Training plan: per-day planned items and labeled training blocks.

CREATE TABLE IF NOT EXISTS planned_items (
    id         SERIAL PRIMARY KEY,
    plan_date  DATE NOT NULL,
    item_type  TEXT NOT NULL CHECK (item_type IN ('hangboard', 'climbing', 'workout', 'rest', 'other')),
    title      TEXT NOT NULL,
    details    TEXT,
    source     TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'coach')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_planned_items_date ON planned_items(plan_date);

CREATE TABLE IF NOT EXISTS training_blocks (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    focus      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_date >= start_date)
);
