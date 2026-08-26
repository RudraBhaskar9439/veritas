# Phase 11 verification report

- Status: deterministic forty-scenario evaluation passed; live latency/cost benchmark partial
- Verified locally: 2026-08-21
- Local command: `node scripts/verify-phase-11.mjs`
- Dataset checksum: `2fa0c41b5da5b9d1c8a6b991798ed81d7434bd479a00db12bf92c1e372cf21c5`
- Accepted implementation commit: `f49bbe1e2db584371e6abe348fbe99c4c6500267`
- Clean GitHub workflow: <https://github.com/RudraBhaskar9439/veritas/actions/runs/32505438197>

## Published deterministic metrics

| Metric | Result | Threshold |
|---|---:|---:|
| Scenarios | 40/40 | 40/40 |
| Overall accuracy | 100% | 100% |
| Meaningful-change recall | 100% | 100% |
| Cosmetic-change suppression | 100% | 100% |
| Registered-lineage precision | 100% | 100% |
| Registered-lineage recall | 100% | 100% |
| Repair-decision accuracy | 100% | 100% |
| Human-edit conflict detection | 100% | 100% |
| False certification | 0% | 0% maximum |
| Offline external API calls | 0 | 0 |

All five strata pass 8/8 cases. A representative local run completed in 2.209 ms, below the 1,000 ms guardrail; this number is workstation-specific and is not presented as production latency.

## Integrity controls

- the evaluator calls production classification, lineage, policy, merge, and certificate validators;
- the scenario corpus contains no `actual` outputs;
- committed results are compared through a canonical hash;
- scenario count and IDs must remain exactly forty and unique;
- dataset checksum and hard thresholds are committed separately;
- live Cloud cost is explicitly pending.

## Pending live metrics

Real production runs now prove Workspace semantic-change handling and native repair correctness. The final-release clean run was detected at 08:48:03 UTC and certified at 08:49:20 UTC. Multiple other clean and recovered certificates are listed in [`../submission/live-proof-report.md`](../submission/live-proof-report.md). The sample is not yet sufficient for a defensible p50/p95, and Gemini token totals and delayed Cloud billing cost remain unclaimed.
