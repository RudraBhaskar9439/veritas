# Veritas

**AI created the work. Veritas keeps it true.**

Veritas is a continuous evidence-integrity agent for AI-created knowledge work. It records claim-level provenance when a decision packet is created, watches registered evidence for meaningful changes, calculates the downstream blast radius, performs minimal repairs across Google Workspace artifacts, preserves human edits, and independently verifies the repaired packet.

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
  -> policy/approval gate
  -> minimal cross-artifact execution
  -> independent verification
  -> scoped integrity certificate
```

## Current status

Phases 0 and 1 are accepted. Phase 2's OAuth security, encrypted credential custody, SQL persistence, and Workspace capability contracts pass locally; its real Google Cloud and Workspace integration gate is waiting for the preview project ID. Phases 3-5 provide deterministic packet generation, durable change capture, and registered-lineage blast radius. Phase 6's typed repair planner, deterministic safety policy, human approval boundary, and idempotent SQL/API contracts pass locally and in CI. Google-dependent end-to-end gates remain open.

See:

- [Product contract](docs/product-contract.md)
- [Canonical demo scenario](docs/demo-scenario.md)
- [Phase gates](docs/phases.md)
- [Verification strategy](docs/verification-strategy.md)
- [Claim Manifest decision record](docs/architecture-decisions/0001-claim-manifest.md)

## Verification

```bash
node scripts/verify-phase-0.mjs
node scripts/verify-phase-1.mjs
node scripts/verify-phase-2.mjs
node scripts/verify-phase-3.mjs
node scripts/verify-phase-4.mjs
node scripts/verify-phase-5.mjs
node scripts/verify-phase-6.mjs
```

Accepted phase evidence is recorded under [`docs/verification`](docs/verification).
