BEGIN;

CREATE TABLE drive_change_operation_batches (
    operation_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    stream_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'ready')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX drive_change_operation_batches_stream_idx
    ON drive_change_operation_batches (subject, stream_id);

CREATE TABLE drive_change_operation_snapshots (
    operation_id TEXT NOT NULL REFERENCES drive_change_operation_batches(operation_id),
    snapshot_id TEXT NOT NULL REFERENCES evidence_snapshots(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (operation_id, snapshot_id)
);

COMMIT;
