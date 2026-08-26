# ADR 0015: Route customer email through manifest-bound authority

- Status: Superseded by ADR 0017
- Date: 2026-08-26

## Context

A customer email often contains the newest operational fact, but a general inbox agent that searches for a likely Task has an unacceptable confused-deputy boundary. Sender spoofing, prompt injection, ambiguous intent, concurrent human edits, and a model selecting the wrong workspace object could all turn a convenient automation into an uncontrolled mutation surface.

The product also needs a demo a judge can verify in real systems: send an ordinary email from a second account, see one existing Google Task change, and inspect evidence showing why only that Task was allowed to change.

## Decision

An operator may create an email-to-task workflow only from an exact claim→Google Task edge in the latest Claim Manifest owned by their authenticated account. Registration records the connected mailbox, one normalized authorized sender, a deterministic non-secret routing key, packet/manifest/claim/artifact identities, and exact Task/list resource IDs.

Gmail `users.watch` publishes mailbox history cursors to a dedicated Pub/Sub topic. Gmail's system publisher has publisher access only to that topic. Pub/Sub invokes ingress with a dedicated service-account OIDC token; ingress verifies its audience, email, and verified-email claim before decoding the notification. Ingress stores only a durable operation reference. The private worker re-reads Gmail history using the connected user's KMS-protected OAuth credential.

The worker checks active status, exact sender, exact recipient, exact routing key, deterministic risk policy, structured extraction confidence, and the Task's ETag. Gemini may return only a proposed natural Task title and note. It cannot select the Task or call a tool. The write preserves human notes and replaces only a delimited Veritas-owned block. Every message becomes an idempotent content-addressed event receipt; the raw body is represented by a SHA-256 proof and is not returned to the browser.

Gmail watches are renewed before expiry. Operators can pause a workflow; paused status is enforced both in the repository query and again in the processor.

## Consequences

- The system deliberately cannot act on an arbitrary email without prior registration.
- Customers must preserve a short route token in the subject. This visible constraint makes the authority boundary explainable and testable.
- A connected account must re-consent to the bounded `gmail.readonly` scope. Full mailbox control is never requested.
- Wrong senders and non-actionable requests create no Task mutation; sensitive or ambiguous requests are escalated.
- Concurrent Task edits fail their ETag precondition and are never overwritten.
- The feature remains useful for support, onboarding, field service, scheduling, and account operations without turning the model into an unconstrained inbox agent.
