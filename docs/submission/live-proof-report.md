# Live production proof report

- Proof date: 2026-08-27
- Google Cloud project: `project-c0f0f832-e02b-4eac-ae2`
- Region: `us-central1`
- Accepted application release commit: `39b337f`
- Public Command Center: <https://veritas-preview-web-602044424209.us-central1.run.app/>
- Cloud Build: `4171eeb9-70dd-4882-b526-30dd74db40c1` (`SUCCESS`)
- Migration execution: `veritas-preview-migrations-6stz6` (`Completed`)
- Release verification: local full suite and live end-to-end proof passed; the proof-only successor commit carries the refreshed rehearsal record.

## Immutable release binding

| Component | Cloud Run revision | Image digest |
|---|---|---|
| API | `veritas-preview-api-00038-d9c` | `sha256:eea9b0791a63c3493d6288d06abbde6d44a3a7b0c5c73f25736db17906d5be88` |
| Drive ingress | `veritas-preview-ingress-00038-f7k` | `sha256:eea9b0791a63c3493d6288d06abbde6d44a3a7b0c5c73f25736db17906d5be88` |
| Worker | `veritas-preview-worker-00038-279` | `sha256:eea9b0791a63c3493d6288d06abbde6d44a3a7b0c5c73f25736db17906d5be88` |
| Web | `veritas-preview-web-00023-78p` | `sha256:7c4d578839cae1bf4db4d12aa115fb60a17bfa5e1b73f79f47cf8fd8680c02c3` |

The public root and `/health/ready` both returned HTTP 200 without an authenticated application session. PostgreSQL 16 has automated backups and point-in-time recovery enabled. The evidence bucket `project-c0f0f832-e02b-4eac-ae2-veritas-preview-snapshots` has object versioning and seven-day soft delete. Pub/Sub topics, the Cloud Tasks repair queue, Secret Manager, and the enabled `workspace-credentials` KMS key are present.

Release `39b337f` adds a durable human authority boundary for ambiguous customer email. An escalated request now exposes the exact proposed Task title and note, accepts only an authenticated approve or reject decision, locks the event before the external write, re-reads the Task and enforces its current ETag, preserves human-authored notes, recovers idempotently after an interrupted write, and binds the inbound receipt and review outcome into a separate SHA-256 review receipt. The complete twelve-phase local gate passes with 232 backend tests, 20 frontend tests, 90.00% coverage, 40/40 evaluation scenarios, and 5/5 deterministic rehearsals.

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
| `3053E54BC7DB` | verified | Clean `72c687c` run; one natural-language Google Task updated in place, detected 09:50:15 UTC, certified 09:51:12 UTC |

Certificate `3053E54BC7DB` independently verified all 13 registered targets, all five protected projections, eight monitored claims, and six pinned evidence versions on `72c687c`. The run changed `Metrics!B17` from 4% to 6%, passed two human approvals, updated the same active Google Task from **Increase acquisition spend** to **Pause the planned increase in acquisition spend**, preserved a single active task and 19 recoverable completed rehearsal tasks, and certified in 57 seconds. The UI and stored certificates use scoped language: the packet is consistent only within its registered boundary.

## Real failure and recovery evidence

Three naturally occurring Gemini dependency outages exercised the production recovery path. The final-release run beginning at 08:51:11 UTC created original operation `op-701ab239-cd91-53f4-b3b2-2f45c40cb047`. It retried attempts 1–5 with bounded delays of 10, 15, 25, and 44 seconds, then entered dead-letter quarantine with diagnostic fingerprint `786295b2ce2b3c9877f7a432`. The UI displayed the exact original operation and a packet-scoped **Replay safely** action; unrelated packet failures were excluded. Audited replay created linked operation `op-74529279-0e51-56b0-bb46-d4cfafb94ea2`, which succeeded on its first attempt after dependency recovery and ultimately issued certificate `74EC21579183`. The original row remained immutable throughout.

Earlier recovery proof used original operation `op-97e6fecd-d95a-5976-93ff-2dc7b7ef1094` and linked replay `op-1b47d16a-6307-549b-b234-20759d732fc9`. A second recovered incident used original `op-22b51355-5867-5274-a07b-e841842f01e3` and linked replay `op-0cd53da0-ee03-539b-800a-8486e83d49c2`, ultimately issuing certificate `A70E9EFE1D02`.

This proves actual dependency retry, quarantine, immutable failure records, audited replay, and recovery. It does not replace the still-unrecorded separate live injections for Cloud Run termination, OAuth expiry, provider 429, or partial native write; those cases are covered by automated failure tests and remain marked partial in the proof manifest.

## Honest remaining proof

- Five **consecutive clean** production runs have not been achieved because real Gemini outages interrupted the streak. Multiple clean and recovered runs are listed instead of being relabelled.
- Desktop hosted-browser semantics, refresh persistence, visible approvals, real-time incident updates, and overflow checks passed. At 1280×720 the final incident had one `main`, one H1, seven headings, thirteen labelled buttons, zero images without `alt`, one skip link, one live region, and no horizontal overflow. The 390×844 hosted phone audit on 2026-08-27 also had one `main`, one H1, zero unlabeled buttons, zero images without `alt`, one skip link, one live region, and no horizontal overflow; keyboard-only Enter navigation successfully exposed the Blast radius and Verification views.
- Exact p50/p95, Gemini token totals, and Cloud billing cost are not claimed while samples are incomplete and billing reporting is delayed.
- The continuous demo recording, upload, and final Devpost submission require the entrant and are not represented as complete.
