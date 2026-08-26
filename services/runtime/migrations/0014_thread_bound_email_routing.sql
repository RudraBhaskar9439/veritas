BEGIN;

CREATE TABLE email_task_thread_bindings (
    binding_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    workflow_id TEXT NOT NULL REFERENCES email_task_workflows(workflow_id),
    gmail_thread_id VARCHAR(255) NOT NULL,
    bootstrap_message_id VARCHAR(255),
    subject_line VARCHAR(998) NOT NULL,
    source VARCHAR(32) NOT NULL CHECK (source IN ('company_started', 'operator_bound')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT email_task_thread_subject_uq UNIQUE (subject, gmail_thread_id)
);

CREATE INDEX email_task_thread_workflow_idx
    ON email_task_thread_bindings(workflow_id, created_at);

CREATE TABLE email_task_unmatched_requests (
    request_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    gmail_message_id VARCHAR(255) NOT NULL,
    gmail_thread_id VARCHAR(255) NOT NULL,
    mailbox_email VARCHAR(320) NOT NULL,
    sender VARCHAR(320) NOT NULL,
    recipient VARCHAR(320) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('pending', 'bound')),
    bound_workflow_id TEXT REFERENCES email_task_workflows(workflow_id),
    receipt_checksum CHAR(64) NOT NULL,
    request_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT email_task_unmatched_message_uq UNIQUE (subject, gmail_message_id)
);

CREATE INDEX email_task_unmatched_subject_idx
    ON email_task_unmatched_requests(subject, status, created_at DESC);

DO $$
DECLARE
    api_role TEXT;
    api_count INTEGER;
    worker_role TEXT;
    worker_count INTEGER;
BEGIN
    SELECT MIN(rolname), COUNT(*)
    INTO api_role, api_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-api@%.iam';

    SELECT MIN(rolname), COUNT(*)
    INTO worker_role, worker_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-worker@%.iam';

    IF api_count <> 1 OR worker_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one API and worker IAM database role';
    END IF;

    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE ON TABLE email_task_thread_bindings, email_task_unmatched_requests TO %I',
        api_role
    );
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE ON TABLE email_task_thread_bindings, email_task_unmatched_requests TO %I',
        worker_role
    );
END
$$;

COMMIT;
