BEGIN;

CREATE TABLE IF NOT EXISTS workspace_credentials (
    subject VARCHAR(255) PRIMARY KEY,
    email VARCHAR(320) NOT NULL,
    encrypted_payload BYTEA NOT NULL,
    key_resource VARCHAR(1024) NOT NULL,
    scopes TEXT NOT NULL,
    connected_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_authorization_attempts (
    state_hash CHAR(64) PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS oauth_authorization_attempts_expiry_idx
    ON oauth_authorization_attempts (expires_at);

COMMIT;
