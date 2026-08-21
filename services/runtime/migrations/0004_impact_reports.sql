BEGIN;

CREATE TABLE IF NOT EXISTS impact_reports (
    report_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    packet_id VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    idempotency_key VARCHAR(1024) NOT NULL UNIQUE,
    input_digest CHAR(64) NOT NULL,
    checksum CHAR(64) NOT NULL,
    report_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT impact_reports_version_uq UNIQUE (subject, packet_id, version)
);

CREATE INDEX IF NOT EXISTS impact_reports_packet_idx
    ON impact_reports (subject, packet_id);

COMMIT;
