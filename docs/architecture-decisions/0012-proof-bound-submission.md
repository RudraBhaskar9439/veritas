# ADR 0012: Bind every submission claim to inspectable proof

- Status: accepted for pre-deployment submission preparation
- Date: 2026-08-21

## Context

Hackathon demos reward clarity, but a polished replay can accidentally imply that simulated or local behavior is already production evidence. Veritas's own product promise is evidence integrity, so its submission must apply the same standard to itself.

## Decision

Phase 12 separates three kinds of evidence:

1. **Implemented and CI-verified:** deterministic runtime, web experience, infrastructure definitions, containers, failure handling, and forty-scenario benchmark.
2. **Automated offline rehearsal:** timing, narrative order, fixture invariants, UI proof values, benchmark status, and explicit pending-state honesty repeated five times.
3. **Pending live proof:** public Cloud Run URL, real Workspace generation and mutation, Cloud SQL/Tasks/Pub/Sub behavior, browser audit, live latency/cost, and five clean end-to-end rehearsals.

The Devpost draft cannot represent a partial `cloud-proof-manifest.json` entry as complete. Every substantive product claim has a named inspectable artifact in the claim-to-evidence matrix. The recorded demo must be a continuous real product run; mocks may appear in tests but never as Workspace mutations, agent events, Cloud status, or result graphs in the video.

The demo contract is limited to 238 seconds and contains twelve contiguous beats. The automated rehearsal checks that the narrative remains aligned with the canonical 4% → 9% incident, exact blast radius, typed repair plan, Command Center coverage, independent checks, and published benchmark.

## Consequences

- The current repository contains a complete recording and submission package without pretending the cloud deployment exists.
- Five deterministic offline rehearsals prove package consistency, not presentation skill or live API reliability.
- Real Cloud and Workspace proof now exists. Five consecutive clean timed rehearsals and the final video remain unfinished because external Gemini outages interrupted the streak and the entrant must record the final continuous run.
- Any later product change that alters the canonical proof invalidates the rehearsal checksum and must update the script and evidence matrix intentionally.
