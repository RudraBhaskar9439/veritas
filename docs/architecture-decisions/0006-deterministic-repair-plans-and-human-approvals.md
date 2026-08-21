# ADR 0006: Separate deterministic repair plans from human approval events

- Status: accepted for pre-live implementation
- Date: 2026-08-21

## Context

A blast radius says which registered claims depend on changed evidence; it does not authorize a mutation. A safe repair must reproduce each claim from the exact transformation version and inputs, respect artifact mutability, preserve a base revision for later merge checks, and prevent an agent from approving its own consequential action.

The original Claim Manifest retained only a transformation name and discarded artifact revision IDs. That was sufficient for impact traversal but insufficient for reproducible repair. It also treated the previous-quarter churn value as hidden transformation context instead of registered evidence.

## Decision

The Claim Manifest now preserves:

- a versioned deterministic transformation and its non-secret parameters for every generated claim;
- every dynamic transformation input as a separate registered source edge;
- the actual writer-returned base revision for every artifact.

Repair planning loads the exact checksummed Claim Manifest and impact report, then selects immutable source snapshots causally available at the impact event. Changed sources use the exact snapshots named by the impact report. Unchanged inputs use the newest snapshot no later than that event. Snapshot bytes are re-hashed, canonicalized, and matched to their persisted metadata before their registered anchor value enters a transformation.

The deterministic policy order is:

| Artifact boundary | Claim risk | Result |
|---|---|---|
| Immutable Gmail message | any | create a correction draft; never mutate or send |
| Other immutable artifact | any | block for manual review |
| Draft-only artifact | any | draft-only action |
| Editable artifact | informational or reversible | eligible for automatic execution |
| Editable artifact | decision-changing or irreversible | require human approval |

The plan is immutable, versioned, checksummed, and has a stable execution key per step. Human decisions are separate authenticated records with append-only idempotency events. The `veritas-agent` principal is explicitly forbidden from approving a plan. Replaying an identical request returns the existing record; reusing a request ID with different content is a conflict.

## Consequences

- Gemini may later help explain a repair, but it cannot change lineage, recompute deterministic claims, override a policy disposition, or manufacture approval.
- A sent email becomes a correction draft, never an edited or automatically sent message.
- Approval applies only to the exact claim-bound steps listed in the immutable plan.
- Execution remains disabled in Phase 6. Docs, Slides, Gmail, and Tasks adapters plus three-way merge are Phase 7 gates.
- The live gate still requires real Google revisions, snapshot objects, and authenticated human identities before the recorded demo.
