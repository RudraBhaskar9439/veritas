CREATE TABLE repair_runs (
    run_id VARCHAR(255) PRIMARY KEY,
    subject VARCHAR(255) NOT NULL,
    plan_id VARCHAR(255) NOT NULL REFERENCES repair_plans(plan_id),
    packet_id VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(1024) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX repair_runs_plan_idx ON repair_runs(subject, plan_id);

CREATE TABLE repair_run_steps (
    run_id VARCHAR(255) NOT NULL REFERENCES repair_runs(run_id),
    step_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    record_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, step_id)
);

CREATE TABLE repair_run_step_events (
    event_id VARCHAR(255) PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL REFERENCES repair_runs(run_id),
    step_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    record_json TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX repair_run_step_events_run_idx ON repair_run_step_events(run_id);
