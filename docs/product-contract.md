# Product contract

## Product statement

Veritas is a transactional integrity runtime for AI-created knowledge work. It keeps registered claims in a Decision Packet consistent with their registered evidence while preserving human authorship and maintaining a complete audit trail.

## Initial user

A knowledge worker who creates an executive or operational packet from changing information and distributes the resulting claims through multiple Google Workspace artifacts.

## Initial Decision Packet

The hackathon vertical is a Q3 Executive Review composed of:

- structured evidence in Google Sheets;
- supporting policy or narrative evidence in Google Docs;
- an executive memo in Google Docs;
- an executive deck in Google Slides;
- an investor communication in Gmail;
- operational follow-up in Google Tasks.

## Core invariant

For every monitored claim, Veritas can answer:

1. What exact evidence version supports it?
2. What deterministic transformation, if any, produced it?
3. Where does the claim appear?
4. What changed since the last verified state?
5. Which repair was proposed or executed?
6. Which human-authored regions were preserved?
7. Which independent checks passed before certification?

## Trust boundaries

- `registered` lineage is captured during generation or explicitly confirmed by a user.
- `candidate` lineage is model-inferred and cannot be certified until confirmed.
- Gemini 2.5 Flash reviews the already registered impact and typed plan through the Google Gen AI SDK. It may veto ambiguous autonomous work, but it cannot add scope, change deterministic policy, approve a repair, or issue a certificate.
- Deterministic code owns calculations, versions, graph traversal, policy enforcement, API mutations, idempotency, and certificate eligibility.
- Consequential or irreversible actions require approval or remain draft-only.

## Certification language

Allowed:

> All monitored claims in this Decision Packet are consistent with their registered evidence versions as of the stated timestamp.

Forbidden:

- This document is completely true.
- Veritas guarantees correctness.
- Every claim in this artifact has been verified, unless coverage is exactly 100% and explicitly shown.

## P0 capabilities

1. Generate or register a Decision Packet and versioned Claim Manifest.
2. Watch registered Google Drive resources asynchronously.
3. Snapshot and semantically classify changes.
4. Traverse registered claim-to-artifact lineage.
5. Produce a typed, policy-checked repair plan.
6. Patch real Docs, Slides, Gmail drafts/corrections, and Tasks.
7. Preserve unrelated human edits with three-way merge and preconditions.
8. Independently verify the repaired packet.
9. Issue a scoped Evidence Integrity Certificate only after all checks pass.
10. Resume safely after duplicate events and partial failures.

## Explicit non-goals for the hackathon

- Universal fact checking
- Arbitrary Drive-wide dependency discovery
- Native mobile application
- Microsoft 365 or Slack integrations
- Autonomous sending of correction emails
- Organization-wide compliance certification
- Large multi-tenant enterprise agent registry

## Success definition

The recorded demonstration must show a real Sheet change producing a persisted event, a correct four-claim blast radius, minimal repair of five real downstream artifacts, preservation of a human-authored paragraph, creation of a correction draft for an already-sent message, independent verification, and a scoped certificate on Google Cloud.
