BEGIN;

ALTER TABLE email_task_events
    ADD COLUMN review_receipt_checksum CHAR(64);

ALTER TABLE email_task_events
    DROP CONSTRAINT email_task_events_status_check;

ALTER TABLE email_task_events
    ADD CONSTRAINT email_task_events_status_check
    CHECK (status IN ('received', 'ignored', 'escalated', 'reviewing', 'rejected', 'applied'));

DO $$
DECLARE
    api_role TEXT;
    api_count INTEGER;
BEGIN
    SELECT MIN(rolname), COUNT(*)
    INTO api_role, api_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-api@%.iam';

    IF api_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one API IAM database role';
    END IF;

    EXECUTE format('GRANT SELECT, UPDATE ON TABLE email_task_events TO %I', api_role);
END
$$;

COMMIT;
