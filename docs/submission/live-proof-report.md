# Live production proof report

- Proof date: 2026-08-27
- Google Cloud project: `project-c0f0f832-e02b-4eac-ae2`
- Transaction-plane region: `us-central1`
- Vertex inference location: `global`
- Accepted application release commit: `5425b0c`
- Public Command Center: <https://veritas-preview-web-602044424209.us-central1.run.app/>
- Cloud Build: `00da295d-10e2-4748-9f64-9eebdc15f839` (`SUCCESS`)
- GitHub workflow: [verified-build 33032292084](https://github.com/RudraBhaskar9439/veritas/actions/runs/33032292084) (`SUCCESS`)
- Migration execution: `veritas-preview-migrations-h8xqg` (`Completed`)
- Gemini 3.5 production-identity proof: `veritas-preview-model-probe-hwgqd` (`Completed`)
- Release verification: local full suite, CI, container builds, migration ledger, public smoke checks, worker-identity Gemini proof, and earlier live Workspace end-to-end proof passed.

## Immutable release binding

| Component | Cloud Run revision | Image digest |
|---|---|---|
| API | `veritas-preview-api-00039-2g9` | `sha256:5f3d1f2f48fc8ad194ace4fe451fb472866c559327320378d8745b28863ae0d8` |
| Drive ingress | `veritas-preview-ingress-00039-t6h` | `sha256:5f3d1f2f48fc8ad194ace4fe451fb472866c559327320378d8745b28863ae0d8` |
| Worker | `veritas-preview-worker-00039-mmg` | `sha256:5f3d1f2f48fc8ad194ace4fe451fb472866c559327320378d8745b28863ae0d8` |
| Web | `veritas-preview-web-00024-twb` | `sha256:1c817e345ebab89305f4962295363f65281f708de34f84ea87e6aeee94f5de5f` |

The public root, web readiness, same-origin API, and control API readiness returned HTTP 200 after the rollout. PostgreSQL 16 has automated backups and point-in-time recovery enabled. The evidence bucket `project-c0f0f832-e02b-4eac-ae2-veritas-preview-snapshots` has object versioning and seven-day soft delete. Pub/Sub topics, the Cloud Tasks repair queue, Secret Manager, and the enabled `workspace-credentials` KMS key are present.

Release `5425b0c` carries the durable human authority boundary for ambiguous customer email and upgrades the production agent to the contest-mandated `gemini-3.5-flash` through Google Gen AI SDK v2. The private worker is configured for Vertex AI's supported `global` inference endpoint while stateful services remain in `us-central1`. One-shot execution `veritas-preview-model-probe-hwgqd` ran the exact `GeminiReviewGateway` from the immutable runtime image as the production worker service account and logged a schema-valid `proceed` result recognizing exactly `claim-1`; it exited zero. The temporary probe job was then deleted without weakening IAM, while its Cloud execution and logs remain. The complete twelve-phase local gate and GitHub workflow pass with 232 backend tests, 20 frontend tests, 90.00% coverage, 40/40 evaluation scenarios, and 5/5 deterministic rehearsals.

The prior full Workspace certificates below were generated before this model upgrade and therefore correctly retain their historical Gemini 2.5 receipts. A fresh unedited submission-video run must show the current Gemini 3.5 release; the worker-identity probe proves the current image, identity, endpoint, model, and structured-output contract are operational, but it is not mislabeled as a full cross-Workspace repair run.

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
