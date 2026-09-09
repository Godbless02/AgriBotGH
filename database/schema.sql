-- Database Phase 1: persistent AgriBotGH user accounts only.
-- Credentials are supplied exclusively through DATABASE_URL on the backend.
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username VARCHAR(30) NOT NULL,
    username_normalized VARCHAR(30) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    preferred_language VARCHAR(2) NOT NULL DEFAULT 'en'
        CHECK (preferred_language IN ('en', 'tw')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NULL
);
