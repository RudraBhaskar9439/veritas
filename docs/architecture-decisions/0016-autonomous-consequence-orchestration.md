# ADR 0016: Autonomous consequence orchestration and live incident projection

## Status

Accepted for preview.

## Context

The individual Veritas phases were production-capable, but a judge-visible product requires the real change event to advance those phases without hand-operated API calls. Approval also cannot be implemented as three unrelated browser requests: a dropped connection after recording a decision could strand the durable run before continuation or verification. Finally, a polished Command Center is not evidence if its graph is assembled from frontend fixtures.

## Decision

The private worker groups newly meaningful evidence snapshots by Decision Packet and derives one stable correlation root from the durable Drive operation. It automatically invokes registered impact analysis, typed repair planning, a Gemini 3.5 Flash safety review through Google's Gen AI SDK, guarded execution, and independent verification. Gemini receives only the registered impact and deterministic policy summary, returns a schema-constrained `proceed` or `escalate` decision, and must echo the exact affected claim set. A mismatched scope, invalid response, or ambiguous authority fails closed. Cosmetic, duplicate, and baseline snapshots do not enter the lifecycle. A run that reaches a model or human authority boundary cannot be certified.

The authenticated Command Center exposes one idempotent decision-and-continue action. Before recording the decision it reconstructs the subject-scoped incident and proves that the approval, repair plan, and run are bound together. A retry with the same request is safe: the approval event is reused, terminal mutation steps are skipped, and verification reuses its checksummed result.

The Command Center read model is a projection over the checksummed manifest, impact report, repair plan, approvals, latest execution journal, causal evidence snapshots, verification report, and integrity certificate. Missing evidence or checksum mismatches fail closed. Offline judge data is a separate explicitly selected mode and is never a network fallback.

## Consequences

- A real Drive change is sufficient to start the complete autonomous product loop.
- The required Gemini/Google agent-framework use is material and inspectable without giving the model mutation authority.
- Human authority pauses, rather than breaks, the durable agent run.
- Approval, continuation, and verification can recover from client disconnects without repeating completed writes.
- The UI cannot claim repaired or verified state unless the corresponding durable records exist.
- Remaining acceptance work requires deployed Google Cloud and Workspace resources; it cannot be replaced by local fixtures.
