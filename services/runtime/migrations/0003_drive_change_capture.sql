BEGIN;

CREATE TABLE IF NOT EXISTS drive_watch_streams (
    stream_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL UNIQUE,
    page_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS drive_watch_channels (
    channel_id VARCHAR(64) PRIMARY KEY,
    stream_id VARCHAR(255) NOT NULL REFERENCES drive_watch_streams(stream_id),
    state VARCHAR(32) NOT NULL CHECK (state IN ('provisioning', 'active', 'retiring', 'stopped', 'failed')),
    google_resource_id VARCHAR(255),
    expiration TIMESTAMPTZ NOT NULL,
    replaces_channel_id VARCHAR(64),
    sync_received BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS drive_watch_channels_renewal_idx
    ON drive_watch_channels (state, expiration);

CREATE TABLE IF NOT EXISTS drive_notifications (
    channel_id VARCHAR(64) NOT NULL REFERENCES drive_watch_channels(channel_id),
    message_number BIGINT NOT NULL CHECK (message_number >= 1),
    google_resource_id VARCHAR(255) NOT NULL,
    resource_state VARCHAR(64) NOT NULL,
    resource_uri TEXT NOT NULL,
    changed TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (channel_id, message_number)
);

CREATE TABLE IF NOT EXISTS drive_notification_outbox (
    event_id VARCHAR(255) PRIMARY KEY,
    channel_id VARCHAR(64) NOT NULL,
    message_number BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('pending', 'processing', 'published', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (channel_id, message_number)
);

CREATE INDEX IF NOT EXISTS drive_notification_outbox_pending_idx
    ON drive_notification_outbox (status);

CREATE TABLE IF NOT EXISTS registered_evidence_sources (
    subject VARCHAR(255) NOT NULL,
    packet_id VARCHAR(255) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    kind VARCHAR(32) NOT NULL CHECK (kind IN ('google_sheet', 'google_doc')),
    resource_id VARCHAR(255) NOT NULL,
    anchor TEXT NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (subject, packet_id, source_id)
);

CREATE INDEX IF NOT EXISTS registered_evidence_sources_resource_idx
    ON registered_evidence_sources (subject, resource_id);

CREATE TABLE IF NOT EXISTS evidence_snapshots (
    snapshot_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    packet_id VARCHAR(255) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    workspace_version VARCHAR(255) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    semantic_hash CHAR(64) NOT NULL,
    bucket VARCHAR(255) NOT NULL,
    object_name TEXT NOT NULL,
    object_generation VARCHAR(64) NOT NULL,
    delta_kind VARCHAR(32) NOT NULL CHECK (delta_kind IN ('baseline', 'duplicate', 'cosmetic', 'meaningful')),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (subject, packet_id, source_id, workspace_version),
    UNIQUE (subject, packet_id, source_id, content_hash)
);

CREATE INDEX IF NOT EXISTS evidence_snapshots_source_created_idx
    ON evidence_snapshots (subject, packet_id, source_id, created_at DESC);

COMMIT;
