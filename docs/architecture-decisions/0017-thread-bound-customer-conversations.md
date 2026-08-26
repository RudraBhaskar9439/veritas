# ADR 0017: Bind customer replies by Gmail thread

- Status: Accepted
- Date: 2026-08-26

## Context

The original manifest-bound email workflow required customers to preserve a visible `[VX-…]`
subject token. That boundary was deterministic, but it exposed implementation metadata and made a
normal customer responsible for internal routing. Sender-only intent matching would improve the
surface experience by weakening the safety boundary: one customer can have several active tasks,
and a model must never guess which workspace object an email owns.

## Decision

The operator still selects an authorized customer and an exact Claim Manifest edge to a Google
Task. Veritas then sends an ordinary opening email from the connected company mailbox and stores
Gmail's returned thread ID in a subject-scoped binding table. The opening message uses a
deterministic RFC Message-ID; setup retries search for and reuse that message before sending.

Incoming mail is routed by the registered Gmail thread before Gemini runs. The worker then verifies
the exact sender, recipient, active workflow, deterministic risk policy, extraction confidence, and
Task ETag. Gemini may interpret only the requested title and note; it cannot select the Task.

An authorized sender's new, unbound Gmail thread becomes an unmatched request containing metadata,
a body hash, candidate workflow IDs derived from exact sender authority, and a checksummed receipt.
It causes no mutation. An operator can bind that thread to one candidate workflow; future replies
use the same deterministic route.

## Consequences

- Customers send and reply to ordinary email with no Veritas code or special syntax.
- Task ownership remains explainable and manifest-bound rather than similarity-based.
- Conversation creation needs the already-consented Gmail compose scope in addition to read-only
  inbox monitoring; no broader Gmail permission is requested.
- Unrelated authorized mail is visible for triage but fails closed.
- Thread bindings and unmatched receipts are durable, subject-scoped, least-privilege records.
