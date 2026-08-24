# Veritas

**AI created the work. Veritas keeps it true.**

Veritas is a continuous evidence-integrity agent for AI-created knowledge work. It records claim-level provenance when a decision packet is created, watches registered evidence for meaningful changes, calculates the downstream blast radius, performs minimal repairs across Google Workspace artifacts, preserves human edits, and independently verifies the repaired packet.

The production worker uses Gemini 3.5 Flash on Vertex AI through Google's Gen AI SDK as a bounded safety-reasoning gate. Gemini may veto ambiguous work and force escalation, but it cannot expand registered scope, override policy, approve its own action, or certify its own repairs. Every structured model decision is schema-validated, checksummed, and persisted as an inspectable reasoning receipt.

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
  -> Gemini 3.5 bounded safety review
  -> policy/approval gate
  -> minimal cross-artifact execution
  -> independent verification
  -> scoped integrity certificate
```

## Current status

Phases 0 and 1 are accepted. Phase 2's OAuth security, signed application sessions, KMS-encrypted credential custody, automatic token refresh, passwordless Cloud SQL IAM path, SQL persistence, and Workspace capability contracts pass locally. The isolated preview project and its read-only Terraform foundation plan are verified, but its billing account is still disabled and no Cloud resources have been applied. Phases 3-8 implement native Workspace packet creation, immutable change capture, registered-lineage impact analysis, typed policy-bound planning, conflict-aware execution, durable approval continuation, and independent verification. Phase 9's judge-first Command Center now reads subject-scoped checksummed production records; it never silently substitutes demo data, and its approval action advances the durable run through verification. Phase 10 adds durable operation leases, bounded retries, dead-letter quarantine, audited replay, safe telemetry, and security hardening. The production worker automatically advances each meaningful Drive snapshot through impact → plan → execute → verify, while stopping safely at human authority boundaries. A dedicated migration job applies the complete schema under a PostgreSQL advisory lock and immutable checksum ledger. Phase 11 publishes a checksummed forty-scenario benchmark, and Phase 12 provides the credit-independent submission package. Only Cloud deployment, real Google Workspace gates, hosted browser/accessibility proof, live failure injection, five live rehearsals, and the final video/submission remain open.

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
