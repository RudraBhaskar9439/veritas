BEGIN;

CREATE TABLE IF NOT EXISTS claim_manifests (
    manifest_id VARCHAR(255) PRIMARY KEY,
    packet_id VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    idempotency_key VARCHAR(512) NOT NULL UNIQUE,
    input_digest CHAR(64) NOT NULL,
    checksum CHAR(64) NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT claim_manifests_packet_version_uq UNIQUE (packet_id, version)
);

CREATE INDEX IF NOT EXISTS claim_manifests_packet_idx
    ON claim_manifests (packet_id);

COMMIT;
