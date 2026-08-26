BEGIN;

DO $$
DECLARE
    api_role TEXT;
    api_count INTEGER;
    ingress_role TEXT;
    ingress_count INTEGER;
    worker_role TEXT;
    worker_count INTEGER;
BEGIN
    SELECT MIN(rolname), COUNT(*)
    INTO api_role, api_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-api@%.iam';

    SELECT MIN(rolname), COUNT(*)
    INTO ingress_role, ingress_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-ingress@%.iam';

    SELECT MIN(rolname), COUNT(*)
    INTO worker_role, worker_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-worker@%.iam';

    IF api_count <> 1 OR ingress_count <> 1 OR worker_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one API, ingress, and worker IAM database role';
    END IF;

    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I, %I, %I', api_role, ingress_role, worker_role);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE ON TABLE email_task_workflows, gmail_watch_streams TO %I',
        api_role
    );
    EXECUTE format('GRANT SELECT ON TABLE email_task_events TO %I', api_role);
    EXECUTE format('GRANT SELECT ON TABLE email_task_workflows TO %I', ingress_role);
    EXECUTE format('GRANT SELECT ON TABLE email_task_workflows TO %I', worker_role);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE ON TABLE gmail_watch_streams, email_task_events TO %I',
        worker_role
    );
END
$$;

COMMIT;
