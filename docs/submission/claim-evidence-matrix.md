# Submission claim-to-evidence matrix

| Submission claim | Evidence judges can inspect | Acceptance rule |
|---|---|---|
| A Sheet change starts the incident autonomously | Drive notification record, snapshot generation, incident timeline | Real Workspace event; no manual API trigger |
| Exactly four claims and five artifacts are affected | Claim Manifest, impact report, Blast Radius view | Nine registered paths; candidate paths remain zero |
| Repairs are minimal | Before/after registered anchors and execution receipts | Only nine planned anchors change |
| Human authorship is preserved | CFO paragraph plus pre/post protected projection hashes | Hashes match byte-for-byte |
| Sent communication is immutable | Original Gmail message ID and linked unsent correction draft | No send endpoint and no mutation of original |
| The agent cannot self-approve | Approval event with authenticated human principal | Decision-changing steps start only after human approval |
| An interrupted worker resumes safely | Operation events and per-step execution journal | Completed native writes are not repeated |
| Verification is independent | Read-only verifier requests and report checksums | No mutation receipt used as observed truth |
| Certificate scope is honest | Certificate statement, counts, evidence versions, report checksum | All registered coverage complete; no universal-truth language |
| The system runs on Google Cloud | [`live-proof-report.md`](live-proof-report.md), Cloud Run revisions, image digests, Cloud SQL, Storage, Vertex AI, KMS, Logs | Evidence bound to accepted application release `72c687c` |
| Gemini materially participates without controlling safety | Vertex AI call, schema-bound review, exact-scope validator, checksummed SQL receipt, UI receipt | Model can proceed or escalate but cannot add scope or self-approve |
| The demo packet is not hard-coded application behavior | Versioned `/api/v1/packets` contract, generic blueprint models, transformation registry, native artifact adapters, Packet Contract UI | Packet identity, sources, claims, risk policy, and targets are caller-supplied and input-digest bound |
| Evaluation is reproducible | `evaluation/scenarios.json`, checksum, harness, CI log | 40/40 thresholds pass from production decision code |

Proof status is machine-readable in [`cloud-proof-manifest.json`](cloud-proof-manifest.json). Complete and partial evidence are intentionally distinguished; a passing local test is not relabelled as a live injection.
