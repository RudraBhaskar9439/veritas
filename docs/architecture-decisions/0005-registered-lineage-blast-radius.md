# ADR 0005: Compute blast radius only from registered lineage

- Status: accepted
- Date: 2026-08-21

## Context

A model can find documents or sentences that appear related to changed evidence, but topical similarity is not proof of dependence. Using inferred relationships for automatic repair would create convincing false positives, miss deliberately indirect transformations, and make certification impossible to scope.

Veritas already persists the exact source-to-claim and claim-to-artifact anchors captured during packet generation. Phase 4 emits subject-and-packet-scoped meaningful evidence snapshots.

## Decision

The blast-radius engine is deterministic graph traversal over one validated Claim Manifest version:

```text
meaningful evidence snapshot
  -> matching registered source ID
  -> registered claims that explicitly reference that source
  -> registered artifact anchors on those claims
```

Only snapshots classified as `meaningful` enter traversal. Snapshot subject and packet must match the requested manifest boundary, every changed source must exist in that manifest, and only one changed snapshot per source is allowed.

Claims marked `candidate` are counted and surfaced but never enter the affected-claim set, lineage paths, artifact set, automatic mutation, or certification. Wording similarity is not consulted. The output contains every exact source-to-claim-to-artifact-anchor path so the UI and later planner can explain why each artifact is affected.

Impact requests load the latest checksummed manifest and immutable snapshots from SQL, verify that the authenticated Workspace subject owns every registered evidence source, and persist a versioned checksummed report. Request IDs are idempotent; reuse with a different manifest or snapshot set is a conflict.

## Consequences

- False-positive edges cannot be introduced by Gemini or embedding similarity.
- Existing packets need explicit registration before they can be monitored.
- A genuine but unregistered dependency remains outside the blast radius and certificate; coverage must show that limitation.
- Policy decisions such as approval and draft-only correction remain Phase 6 concerns rather than being mixed into graph traversal.
- Reports are reproducible from a manifest ID/version and immutable snapshot IDs.
