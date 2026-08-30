# Judge testing guide

## Public path — no credentials

1. Open <https://veritas-preview-web-602044424209.us-central1.run.app/> in a signed-out browser.
2. Select **Open offline judge demo**. Veritas visibly labels this as demonstration data.
3. Inspect the complete incident in order:
   - **Command center** — the incident outcome, immutable before/after evidence, and detection time;
   - **Live run** — the seven-stage autonomous transaction, persisted Gemini decision, signed execution terminal, and causal graph;
   - **Email → Task** — manifest-bound private Gmail routing into one exact Google Task;
   - **Repair desk** — automatic, human-approval, draft-only, conflict, and recovery actions;
   - **Blast radius** — four affected claims, five artifacts, and only manifest-registered paths;
   - **Proof ledger** — native resource boundaries, content-addressed snapshots, revisions, and preservation hashes;
   - **Verification** — independent re-read of 13/13 registered targets and the scoped certificate;
   - **Architecture** — Google Cloud trust boundaries and the reusable versioned packet contract.
4. Refresh the page, switch to a phone-width viewport, and use the tabs with the keyboard. The walkthrough remains available and responsive.
5. Check <https://veritas-preview-web-602044424209.us-central1.run.app/health/ready>; a healthy deployment returns HTTP 200.

## What is live and what is replayable

The public walkthrough is a deterministic evidence-room view, not a fake authenticated Workspace account. It exists so judges can inspect the entire product without receiving access to the entrant's email or documents. It cannot mutate Google Workspace.

The submission video shows the production path unedited: a real Sheets edit is received by authenticated ingress, the private worker calls Gemini 3.5 Flash on Vertex AI, registered consequences are repaired through native Docs, Slides, Gmail, and Tasks APIs, and the independent verifier re-reads the results. The public Command Center and `/health/ready` endpoint run on Cloud Run. Exact Cloud revisions, immutable image digests, certificates, and limits of the recorded proof are in [`live-proof-report.md`](live-proof-report.md) and [`cloud-proof-manifest.json`](cloud-proof-manifest.json).

## Safety boundaries judges should notice

- Claim dependencies come only from the checksummed Claim Manifest; similarity search cannot authorize a write.
- Gemini can return only a schema-bound `proceed` or `escalate` review over the already-registered scope.
- Decision-changing actions require a human; sent email is immutable and can only produce an unsent correction draft.
- Every native write uses revision or ETag preconditions and preserves unregistered human content.
- The mutation worker cannot certify itself. A separate read-only verifier issues a certificate only for the registered targets it re-read.
- The certificate is scoped evidence integrity, never a claim that an entire document is universally true.

## Repository reproduction

Follow the root [`README.md`](../../README.md) for exact local and Cloud steps. No password, OAuth token, billing identifier, or shared Workspace credential is required to evaluate the public path. If the repository remains private during judging, the entrant must grant `testing@devpost.com` and `cloudhackathons@google.com` access before the deadline.
