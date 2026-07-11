-- AI coach: chat conversations and on-demand recommendations.

CREATE TABLE IF NOT EXISTS coach_conversations (
    id         SERIAL PRIMARY KEY,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES coach_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coach_recommendations (
    id               SERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    context_snapshot JSONB NOT NULL,
    constraint_text  TEXT,
    recommendation   TEXT NOT NULL,
    model            TEXT NOT NULL
);
