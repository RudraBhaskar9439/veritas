CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    kind VARCHAR(80) NOT NULL,
    correlation_id VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(512) NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (
        status IN ('queued', 'running', 'retry_wait', 'succeeded', 'dead_letter')
    ),
    attempt INTEGER NOT NULL CHECK (attempt >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 10),
    available_at TIMESTAMPTZ NOT NULL,
    lease_owner VARCHAR(128),
    lease_expires_at TIMESTAMPTZ,
    last_error_code VARCHAR(80),
    diagnostic_fingerprint VARCHAR(64),
    replay_of TEXT REFERENCES operations(operation_id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (
        (status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    )
);

CREATE INDEX operations_claim_idx ON operations(status, available_at);
CREATE INDEX operations_dead_letter_idx ON operations(subject, status);

CREATE TABLE operation_events (
    event_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    event_type VARCHAR(80) NOT NULL,
    actor TEXT NOT NULL,
    event_json TEXT NOT NULL,
    checksum CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX operation_events_operation_idx
    ON operation_events(operation_id, created_at);
