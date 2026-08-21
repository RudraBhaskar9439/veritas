# Operations recovery runbook

## Alert: operation entered dead-letter quarantine

1. Open the operation using its `operation_id` and `correlation_id`. Do not copy source content, credentials, or payloads into tickets or chat.
2. Inspect the bounded `error_code`, attempt count, diagnostic fingerprint, preceding transition events, repair journal, and source-version status.
3. Classify the cause:
   - dependency restored: token refresh, quota window, or provider availability;
   - input corrected: invalid structured output or unsupported operation kind;
   - human review required: edit conflict, approval, or source movement;
   - code defect: reproducible invariant or adapter failure.
4. Correct the dependency or obtain the required human decision. Never edit the failed operation record.
5. Request replay with an authenticated operator identity, a unique request ID, and a reason of at least 12 characters. Replay creates a new linked operation.
6. Confirm that the new handler revalidates evidence versions, native revisions, policy approvals, and idempotency before any write.
7. Watch for `operation.succeeded`. If the replay returns to quarantine with the same fingerprint, stop replaying and escalate to engineering.
8. After resolution, record the new operation ID, the original ID, the certificate outcome, and whether any human-authored region changed.

## Worker interruption

1. Do not manually reset a `running` operation while its lease is valid.
2. Allow the 60-second lease to expire or verify the worker instance is definitively gone.
3. The next worker tick recovers the lease and increments the attempt. Completed native steps are recovered from their existing idempotency journals.
4. Confirm the operation event stream contains `lease_recovered`, a new `claimed` event, and one terminal transition.

## Retry boundaries

- Default operation budget: five attempts.
- Default backoff: five seconds, exponentially increasing with deterministic bounded jitter.
- Maximum application retry delay: 300 seconds.
- Provider `Retry-After` values are honored only within that cap.
- Repeated human-edit conflicts and source movement are never blindly retried.

## Live proof still required

After Google Cloud access arrives, inject a Cloud Run worker termination, a Cloud Tasks duplicate, a Google 429, an expired OAuth token, and one partial Workspace write. Record Cloud SQL transitions, Cloud Logging events, alert delivery, resumed execution, and the final independently verified certificate.

