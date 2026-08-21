# ADR 0003: Commit manifests only from materialized artifact anchors

- Status: accepted for pre-live implementation
- Date: 2026-08-21

## Context

A Claim Manifest is useful only if its lineage points to the artifacts that were actually created. Predicting Google Docs indexes, Slides object IDs, Gmail message IDs, or Tasks IDs before the APIs return would create plausible but false provenance. Retrying a partially completed packet can also duplicate external artifacts unless every write has a stable identity.

## Decision

Decision Packet generation is an idempotent, fail-closed pipeline:

1. Validate the packet blueprint and every source-to-claim-to-artifact reference.
2. Render registered transformations deterministically from validated source snapshots.
3. Send typed artifact drafts to the Workspace writer with stable per-artifact idempotency keys.
4. Accept resource IDs and claim anchors only from the writer's materialization response.
5. Reject incomplete, duplicated, or unexpected writer results.
6. Persist a versioned Claim Manifest only after every expected artifact and anchor is present.

The manifest stores source identity and version metadata, not source values or transformation context. Its canonical JSON receives a SHA-256 checksum. PostgreSQL serializes version allocation for each packet with a transaction-scoped advisory lock. Replaying the same request and inputs returns the existing manifest; reusing a request ID with different inputs is a conflict.

## Consequences

- Runtime and UI code cannot invent provenance anchors.
- A failed multi-artifact write may leave an external artifact, so each Google adapter must honor its stable idempotency key on retry.
- A changed source snapshot needs a new request ID and creates a new manifest version.
- Manifest persistence is atomic, but Google Workspace cannot participate in that database transaction.
- The local gate can prove orchestration, transformations, validation, and persistence; the phase remains open until real Workspace writers produce and re-open native artifacts.
