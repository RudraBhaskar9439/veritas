# ADR 0010: Durable leases, bounded retry, and audited recovery

- Status: accepted for pre-cloud implementation
- Date: 2026-08-21

## Context

Veritas performs consequential, multi-artifact work. A process can stop after one native write, Google can throttle a request, a token can expire, Gemini can time out, and a human can edit an artifact while repair is underway. Treating all failures as equivalent would either lose work or repeat writes. Logging exception text would also risk leaking Workspace content or credentials.

Cloud Tasks and Pub/Sub provide delivery, but they cannot own Veritas's domain-level idempotency, source-version rules, or repair journals. The runtime therefore needs a durable operation ledger that remains authoritative across duplicate delivery, worker death, retry, quarantine, and operator replay.

## Decision

Phase 10 adds a PostgreSQL-backed operation state machine with five explicit states: `queued`, `running`, `retry_wait`, `succeeded`, and `dead_letter`.

- Enqueue is idempotent over a caller-supplied key and a canonical payload hash. Reusing the key for different work fails closed.
- Claiming an operation acquires a bounded worker lease and increments the attempt count atomically.
- An expired lease returns to the queue without erasing the attempt or the immutable event history.
- Retryable failures use deterministic exponential backoff with bounded jitter and respect a provider retry delay only up to the configured cap.
- Permanent failures and exhausted attempts enter dead-letter quarantine.
- Raw exceptions and operation payloads never enter operational events. Events carry bounded error codes and one-way diagnostic fingerprints.
- Replay requires an authenticated actor, a meaningful reason, and an idempotent request ID. It creates a new operation linked to the immutable dead-lettered original.
- Every transition writes a checksummed event suitable for audit and reconstruction.

The failure taxonomy is explicit. Token expiry, quota exhaustion, model timeout, and partial artifact failure are retryable. Invalid structured output, overlapping human edits, source movement during execution, and unsupported work types are quarantined for review. The downstream handler still owns native API idempotency, three-way merge, and source-version revalidation.

The HTTP boundary now rejects oversized requests, replaces unsafe correlation IDs, emits request duration, disables storage of responses, and sets CSP, permissions, framing, MIME, referrer, and production HSTS headers. Terraform defines payload-free retry/dead-letter log metrics and an alert for any quarantined operation.

## Consequences

- Duplicate delivery cannot create different work under the same idempotency key.
- A crashed worker can be replaced after its lease expires without silently abandoning the operation.
- Operators can recover poison work without modifying history or performing an unaudited retry.
- Diagnostic correlation remains useful without storing exception text or Workspace payloads in logs.
- Cloud Tasks retry is transport-level; the operation ledger remains the domain-level source of truth.
- The alert policy and structured Cloud Logging are deployed. Real Gemini outages proved bounded retries, dead-letter quarantine, packet-scoped recovery, and audited replay. Separate live Cloud Run termination, duplicate-delivery, OAuth-expiry, 429, and partial-write injections remain to be recorded.
