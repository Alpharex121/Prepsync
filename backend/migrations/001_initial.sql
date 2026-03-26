CREATE TABLE IF NOT EXISTS quiz_history (
    id SERIAL PRIMARY KEY,
    room_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    config_params JSONB NOT NULL,
    question_package JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_history_room_id ON quiz_history(room_id);
CREATE INDEX IF NOT EXISTS idx_quiz_history_created_at ON quiz_history(created_at DESC);
