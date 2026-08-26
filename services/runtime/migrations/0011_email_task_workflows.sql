BEGIN;

CREATE TABLE email_task_workflows (
    workflow_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    mailbox_email VARCHAR(320) NOT NULL,
    authorized_sender VARCHAR(320) NOT NULL,
    routing_key VARCHAR(32) NOT NULL,
    packet_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_list_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused')),
    input_digest CHAR(64) NOT NULL,
    workflow_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT email_task_workflows_route_uq UNIQUE (subject, routing_key)
);

CREATE INDEX email_task_workflows_mailbox_idx
    ON email_task_workflows (mailbox_email, status);

CREATE TABLE gmail_watch_streams (
    subject TEXT PRIMARY KEY,
    mailbox_email VARCHAR(320) NOT NULL UNIQUE,
    history_id TEXT NOT NULL,
    expiration TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE email_task_events (
    event_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES email_task_workflows(workflow_id),
    gmail_message_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('received', 'ignored', 'escalated', 'applied')),
    receipt_checksum CHAR(64) NOT NULL,
    event_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT email_task_events_workflow_message_uq
        UNIQUE (workflow_id, gmail_message_id)
);

CREATE INDEX email_task_events_workflow_created_idx
    ON email_task_events (workflow_id, created_at DESC);

COMMIT;
