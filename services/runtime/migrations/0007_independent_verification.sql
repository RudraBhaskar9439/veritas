CREATE TABLE artifact_protection_baselines (
    run_id VARCHAR(255) NOT NULL REFERENCES repair_runs(run_id),
    artifact_id VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    resource_id VARCHAR(255) NOT NULL,
    revision_id VARCHAR(255) NOT NULL,
    anchor_set_hash VARCHAR(64) NOT NULL,
    protected_content_hash VARCHAR(64) NOT NULL,
    baseline_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, artifact_id)
);

CREATE INDEX artifact_protection_baselines_subject_run_idx
    ON artifact_protection_baselines(subject, run_id);

CREATE TABLE verification_reports (
    report_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    run_id VARCHAR(255) NOT NULL REFERENCES repair_runs(run_id),
    plan_id VARCHAR(255) NOT NULL REFERENCES repair_plans(plan_id),
    packet_id VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(1024) NOT NULL UNIQUE,
    input_digest VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    report_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX verification_reports_packet_idx
    ON verification_reports(subject, packet_id);

CREATE TABLE integrity_certificates (
    certificate_id VARCHAR(255) PRIMARY KEY,
    report_id VARCHAR(255) NOT NULL UNIQUE REFERENCES verification_reports(report_id),
    subject VARCHAR(255) NOT NULL,
    packet_id VARCHAR(255) NOT NULL,
    certificate_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL
);
