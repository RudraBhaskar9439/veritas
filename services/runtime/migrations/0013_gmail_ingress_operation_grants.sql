BEGIN;

DO $$
DECLARE
    ingress_role TEXT;
    ingress_count INTEGER;
BEGIN
    SELECT MIN(rolname), COUNT(*)
    INTO ingress_role, ingress_count
    FROM pg_roles
    WHERE rolname LIKE 'veritas-%-ingress@%.iam';

    IF ingress_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one ingress IAM database role';
    END IF;

    EXECUTE format('GRANT SELECT, INSERT ON TABLE operations TO %I', ingress_role);
    EXECUTE format('GRANT INSERT ON TABLE operation_events TO %I', ingress_role);
END
$$;

COMMIT;
