BEGIN;

CREATE TABLE IF NOT EXISTS agent_reviews (
    review_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    operation_id VARCHAR(255) NOT NULL UNIQUE REFERENCES operations(operation_id),
    plan_id VARCHAR(255) NOT NULL REFERENCES repair_plans(plan_id),
    packet_id VARCHAR(255) NOT NULL,
    model VARCHAR(255) NOT NULL,
    prompt_version VARCHAR(255) NOT NULL,
    input_digest CHAR(64) NOT NULL,
    checksum CHAR(64) NOT NULL,
    review_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_reviews_subject_plan_idx
    ON agent_reviews (subject, plan_id, created_at DESC);

COMMIT;
