CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS auth_sessions_user_id_idx
    ON auth_sessions (user_id);
