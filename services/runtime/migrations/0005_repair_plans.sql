CREATE TABLE repair_plans (
    plan_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    packet_id VARCHAR(255) NOT NULL,
    impact_report_id VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL,
    idempotency_key VARCHAR(1024) NOT NULL UNIQUE,
    input_digest VARCHAR(64) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (subject, packet_id, version)
);

CREATE INDEX repair_plans_packet_idx ON repair_plans(subject, packet_id);

CREATE TABLE repair_approvals (
    approval_id VARCHAR(255) PRIMARY KEY,
    plan_id VARCHAR(255) NOT NULL REFERENCES repair_plans(plan_id),
    claim_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    decided_by VARCHAR(255),
    reason TEXT,
    decided_at TIMESTAMPTZ
);

CREATE INDEX repair_approvals_plan_idx ON repair_approvals(plan_id);

CREATE TABLE repair_approval_events (
    event_id VARCHAR(255) PRIMARY KEY,
    idempotency_key VARCHAR(1024) NOT NULL UNIQUE,
    subject VARCHAR(255) NOT NULL,
    plan_id VARCHAR(255) NOT NULL REFERENCES repair_plans(plan_id),
    approval_id VARCHAR(255) NOT NULL REFERENCES repair_approvals(approval_id),
    actor VARCHAR(255) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
