# Veritas

**AI created the work. Veritas keeps it true.**

Veritas is a continuous evidence-integrity agent for AI-created knowledge work. It records claim-level provenance when a decision packet is created, watches registered evidence for meaningful changes, calculates the downstream blast radius, performs minimal repairs across Google Workspace artifacts, preserves human edits, and independently verifies the repaired packet.

The production worker uses Gemini 2.5 Flash on Vertex AI through Google's Gen AI SDK as a bounded safety-reasoning gate. Gemini may veto ambiguous work and force escalation, but it cannot expand registered scope, override policy, approve its own action, or certify its own repairs. Every structured model decision is schema-validated, checksummed, and persisted as an inspectable reasoning receipt.

## Hackathon target

- Primary track: The Taskmaster
- Secondary prize targets: Best Architectural Design, Individual/Hobbyist, Best Multimodal UX
- Demo vertical: Q3 Executive Review decision packet
- Production boundary: real Google Workspace APIs and real Google Cloud services; no simulated actions in the recorded demo

## Non-negotiable loop

```text
evidence change
  -> immutable snapshot
  -> semantic delta
  -> registered lineage traversal
  -> typed repair plan
  -> Gemini 2.5 bounded safety review
  -> policy/approval gate
  -> minimal cross-artifact execution
  -> independent verification
  -> scoped integrity certificate
```

## Current status

Veritas is deployed in Google Cloud project `project-c0f0f832-e02b-4eac-ae2` at [the public Command Center](https://veritas-preview-web-602044424209.us-central1.run.app/). The accepted release commit is `c880e5f`; Cloud Build produced immutable runtime and web images, four Cloud Run services serve those digests, and the production migration job completed successfully. Real Google Workspace runs now generate native Sheets, Docs, Slides, Gmail drafts, and Tasks; a real Sheet edit autonomously drives impact analysis, guarded repair, two human approvals, independent re-read, and a scoped certificate. Live Gemini outages have also exercised bounded retry, dead-letter quarantine, and audited replay. The deterministic forty-scenario benchmark and the complete local verification suite remain green. The repository intentionally reports the five-consecutive-run proof, phone/keyboard accessibility audit, exact live cost and model usage, recorded video, and final Devpost submission as unfinished until their evidence exists.

See:

- [Product contract](docs/product-contract.md)
- [Canonical demo scenario](docs/demo-scenario.md)
- [Phase gates](docs/phases.md)
- [Verification strategy](docs/verification-strategy.md)
- [Claim Manifest decision record](docs/architecture-decisions/0001-claim-manifest.md)
- [Live production proof](docs/submission/live-proof-report.md)
- [Public Command Center](https://veritas-preview-web-602044424209.us-central1.run.app/)

## Verification

```bash
node scripts/verify-phase-0.mjs
node scripts/verify-phase-1.mjs
node scripts/verify-phase-2.mjs
node scripts/verify-phase-3.mjs
node scripts/verify-phase-4.mjs
node scripts/verify-phase-5.mjs
node scripts/verify-phase-6.mjs
node scripts/verify-phase-7.mjs
node scripts/verify-phase-8.mjs
node scripts/verify-phase-9.mjs
node scripts/verify-phase-10.mjs
node scripts/verify-phase-11.mjs
node scripts/verify-phase-12.mjs
```

Accepted phase evidence is recorded under [`docs/verification`](docs/verification).
