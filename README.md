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

Phases 0 and 1 are accepted. Phase 2's OAuth security, signed application sessions, KMS-encrypted credential custody, automatic token refresh, passwordless Cloud SQL IAM path, SQL persistence, and Workspace capability contracts pass locally. The isolated preview project and a 67-resource read-only Terraform foundation plan are verified, but its billing account is still pending and no Cloud resources have been applied. Phases 3-5 provide a real native Workspace packet writer, deterministic packet generation, durable change capture, and registered-lineage blast radius. Phase 6's typed repair planner, deterministic safety policy, human approval boundary, and idempotent SQL/API contracts pass locally and in CI. Phase 7's conflict-aware Workspace execution and durable resume contracts pass pre-live; five real Workspace runs remain mandatory. Phase 8 independently verifies registered coverage, and Phase 9 provides the judge-first evidence room. Phase 10 adds durable operation leases, bounded retries, dead-letter quarantine, audited replay, safe operational telemetry, and security hardening. The production worker now drains Drive's transactional outbox into subject-bound, idempotent change-processing operations on an authenticated schedule. Phase 11 publishes a checksummed forty-scenario benchmark that executes production decision functions. Phase 12 completes the credit-independent demo, architecture, runbook, evidence, rehearsal, and submission package while leaving every live Cloud proof item explicit. The Command Center read model, Cloud deployment, downstream automatic planning/execution composition, and Google-dependent end-to-end gates remain open.

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
node scripts/verify-phase-7.mjs
node scripts/verify-phase-8.mjs
node scripts/verify-phase-9.mjs
node scripts/verify-phase-10.mjs
node scripts/verify-phase-11.mjs
node scripts/verify-phase-12.mjs
```

Accepted phase evidence is recorded under [`docs/verification`](docs/verification).
