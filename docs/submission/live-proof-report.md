# Live production proof report

- Proof date: 2026-08-26
- Google Cloud project: `project-c0f0f832-e02b-4eac-ae2`
- Region: `us-central1`
- Accepted release commit: `c880e5f` (formatter-only successor of the live-run commit `23f802f`)
- Public Command Center: <https://veritas-preview-web-602044424209.us-central1.run.app/>
- Cloud Build: `f43c0551-6494-4689-9a90-3e8ac259535c` (`SUCCESS`)
- Migration execution: `veritas-preview-migrations-pvh24` (`Completed`)

## Immutable release binding

| Component | Cloud Run revision | Image digest |
|---|---|---|
| API | `veritas-preview-api-00030-kc7` | `sha256:523e35c42371de76d80b7df9092aa6dc43e90ddc1ef19eb1e11ba6bd18a54b25` |
| Drive ingress | `veritas-preview-ingress-00030-n8c` | `sha256:523e35c42371de76d80b7df9092aa6dc43e90ddc1ef19eb1e11ba6bd18a54b25` |
| Worker | `veritas-preview-worker-00030-mrr` | `sha256:523e35c42371de76d80b7df9092aa6dc43e90ddc1ef19eb1e11ba6bd18a54b25` |
| Web | `veritas-preview-web-00016-dkd` | `sha256:9971506b01d9050e4dd067d587e3df957c60b534f1bcb3b61baaca7e33c22461` |

The public root and `/health/ready` both returned HTTP 200 without an authenticated application session. PostgreSQL 16 has automated backups and point-in-time recovery enabled. The evidence bucket `project-c0f0f832-e02b-4eac-ae2-veritas-preview-snapshots` has object versioning and seven-day soft delete. Pub/Sub topics, the Cloud Tasks repair queue, Secret Manager, and the enabled `workspace-credentials` KMS key are present.

## Real Workspace happy-path evidence

Each run created a fresh native Workspace packet, then changed the generated Sheet's `Metrics!B17` cell from 4% to 9%. No prompt or manual repair trigger followed that edit. The Drive event produced a content-addressed snapshot, four-claim impact report, nine-step typed repair plan, Gemini 2.5 Flash reasoning receipt, five-artifact repair, two explicit human authority decisions, independent re-read, and scoped certificate.

| Certificate | Result | Notes |
|---|---|---|
| `E84A0AE273CA` | verified | Clean real Workspace run |
| `E89F1CED1640` | verified | Clean real Workspace run |
| `6441A8CEC7E2` | verified | Clean real Workspace run |
| `D7AFE956D741` | verified after recovery | Real Gemini outage; replayed after quarantine |
| `5B4CBC46A1A5` | verified | Clean real Workspace run |
| `49F7524E0957` | verified | Clean real Workspace run |
| `A70E9EFE1D02` | verified after recovery | Second real Gemini outage; replayed after quarantine |
| `370C1A51AD95` | verified | Clean run on final release `23f802f`; detected 08:48:03 UTC, certified 08:49:20 UTC |
| `74EC21579183` | verified after recovery | Final-release outage; detected 08:51:11 UTC, audited replay succeeded, certified 09:02:00 UTC |

Certificate `370C1A51AD95` independently verified all 13 registered targets, all five protected projections, eight monitored claims, and six pinned evidence versions on `23f802f`. Commit `c880e5f` changes only formatter layout in the already-tested packet-scoping query; a clean detached build deployed that successor, the migration completed, public root/readiness checks returned HTTP 200, and recovered certificate `74EC21579183` remained independently verified after rollout. The UI and stored certificates use scoped language: the packet is consistent only within its registered boundary.

## Real failure and recovery evidence

Three naturally occurring Gemini dependency outages exercised the production recovery path. The final-release run beginning at 08:51:11 UTC created original operation `op-701ab239-cd91-53f4-b3b2-2f45c40cb047`. It retried attempts 1–5 with bounded delays of 10, 15, 25, and 44 seconds, then entered dead-letter quarantine with diagnostic fingerprint `786295b2ce2b3c9877f7a432`. The UI displayed the exact original operation and a packet-scoped **Replay safely** action; unrelated packet failures were excluded. Audited replay created linked operation `op-74529279-0e51-56b0-bb46-d4cfafb94ea2`, which succeeded on its first attempt after dependency recovery and ultimately issued certificate `74EC21579183`. The original row remained immutable throughout.

Earlier recovery proof used original operation `op-97e6fecd-d95a-5976-93ff-2dc7b7ef1094` and linked replay `op-1b47d16a-6307-549b-b234-20759d732fc9`. A second recovered incident used original `op-22b51355-5867-5274-a07b-e841842f01e3` and linked replay `op-0cd53da0-ee03-539b-800a-8486e83d49c2`, ultimately issuing certificate `A70E9EFE1D02`.

This proves actual dependency retry, quarantine, immutable failure records, audited replay, and recovery. It does not replace the still-unrecorded separate live injections for Cloud Run termination, OAuth expiry, provider 429, or partial native write; those cases are covered by automated failure tests and remain marked partial in the proof manifest.

## Honest remaining proof

- Five **consecutive clean** production runs have not been achieved because real Gemini outages interrupted the streak. Multiple clean and recovered runs are listed instead of being relabelled.
- Desktop hosted-browser semantics, refresh persistence, visible approvals, real-time incident updates, and overflow checks passed. At 1280×720 the final incident had one `main`, one H1, seven headings, thirteen labelled buttons, zero images without `alt`, one skip link, one live region, and no horizontal overflow. Final phone-width, keyboard-only, and automated accessibility recordings remain partial.
- Exact p50/p95, Gemini token totals, and Cloud billing cost are not claimed while samples are incomplete and billing reporting is delayed.
- The continuous demo recording, upload, and final Devpost submission require the entrant and are not represented as complete.
