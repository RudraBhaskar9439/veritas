# Verified implementation phases

| Phase | Deliverable | Hard gate |
|---|---|---|
| 0 | Private repository, product contract, canonical scenario, schemas, expected impact | `node scripts/verify-phase-0.mjs` |
| 1 | Production monorepo, CI, local services, infrastructure definitions, health checks | lint, types, unit tests, build, local smoke test |
| 2 | Google OAuth, encrypted credential storage, Workspace adapter contracts | auth integration and security tests |
| 3 | Decision Packet generator, Claim Manifest, provenance anchors | real packet generation and manifest validation |
| 4 | Drive watches, renewal, snapshots, deduplication, semantic delta | real change and cosmetic-change tests |
| 5 | Registered lineage traversal and blast-radius API | golden impact fixtures and hard negatives |
| 6 | Typed repair planning, policies, approvals, idempotency | policy matrix and duplicate-plan tests |
| 7 | Docs, Slides, Gmail, Tasks execution and three-way merge | five consecutive real repair runs |
| 8 | Independent verification and integrity certificate | rejection, stale-run, and no-false-certificate tests |
| 9 | Command Center, incident graph, diffs, live timeline, certificate UI | browser E2E, accessibility, refresh recovery |
| 10 | Observability, security, retries, dead letters, recovery | failure-injection and worker-resume suite |
| 11 | Forty-scenario evaluation and published metrics | benchmark thresholds and reproducibility |
| 12 | Four-minute demo, Cloud proof, diagrams, runbook, submission | five clean rehearsals and submission checklist |

No later phase may compensate for a failed earlier gate. Scope is reduced before verification standards are reduced.

