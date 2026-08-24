# Veritas

**Tagline:** When evidence changes, repair every consequence.

> Submission integrity note: this draft becomes final only after every item in `cloud-proof-manifest.json` is complete. Do not remove that gate or claim live evidence early.

## Inspiration

AI can create a memo, deck, email, and action plan in seconds. But when the spreadsheet behind them changes tomorrow, the AI-generated work silently becomes inconsistent. Existing assistants can summarize the new number or remind a person to update documents; they do not know exactly which claims depend on it, safely repair every consequence, preserve human edits, and prove the packet is consistent again.

## What it does

Veritas is a transactional integrity runtime for AI-created knowledge work.

When registered evidence changes, Veritas:

1. captures an immutable evidence version;
2. distinguishes meaningful changes from formatting noise;
3. traverses a versioned claim-level provenance graph;
4. produces a minimal typed repair plan;
5. enforces deterministic approval and immutability policies;
6. repairs registered anchors across Google Docs, Slides, Gmail drafts, and Tasks;
7. preserves unrelated human-authored regions with three-way merge and native preconditions;
8. independently re-reads every registered target; and
9. issues a scoped Evidence Integrity Certificate only after complete verification.

In the demo, changing customer churn from 4% to 9% affects four monitored claims across five artifacts. Veritas repairs the editable consequences, pauses decision-changing actions for a human, creates an unsent correction for the immutable investor email, preserves the CFO’s paragraph, and verifies all thirteen registered targets.

## Why it is different

Veritas does not search the Drive for text that looks similar. Relationships are registered when the packet is generated and stored in a checksummed Claim Manifest. Model-inferred candidate relationships cannot authorize a write or enter a certificate.

The repair agent also cannot certify itself. An independent, read-only verifier recomputes claims from immutable evidence snapshots and re-reads native Workspace artifacts. The certificate says only that monitored claims match their registered evidence versions—not that an entire document is universally true.

## How we built it

- **Gemini 3.5 Flash on Vertex AI + Google Gen AI SDK:** schema-bound consequence safety review. Gemini may stop ambiguous work, but exact scope, policy, approvals, writes, and certification remain deterministic.
- **Cloud Run:** separately deployable control API, event ingress, agent worker, and Command Center.
- **Cloud SQL for PostgreSQL:** Claim Manifests, impact reports, repair plans, approvals, execution journals, verification reports, durable worker leases, dead letters, and audit events.
- **Pub/Sub and Cloud Tasks:** asynchronous change capture and bounded command delivery.
- **Cloud Storage:** immutable content-addressed evidence and pre-repair snapshots.
- **Cloud KMS and Secret Manager:** encrypted Google credential custody and secret isolation.
- **Google Workspace APIs:** Drive, Sheets, Docs, Slides, Gmail, and Tasks.
- **React and TypeScript:** a judge-first incident evidence room with diffs, blast radius, receipts, and certificates.

## Architectural discipline

Gemini reasons inside a narrow authority envelope; deterministic code controls the transaction. The model reviews the registered impact and typed policy, must echo the exact claim set, and can only return `proceed` or `escalate`. Calculations, versions, graph traversal, policy, approvals, native write preconditions, idempotency, worker leases, checksums, protected-region hashes, and certificate eligibility remain outside the model. Its structured decision is persisted as a checksummed reasoning receipt.

Every operation is idempotent and resumable. Retryable failures use bounded deterministic backoff. Permanent or exhausted failures enter dead-letter quarantine, and operator replay creates a new audited operation linked to the immutable original.

## Challenges

The hardest problem was not generating better content. It was preserving authorship while changing only registered claims across APIs with different revision and mutability semantics. We solved it with anchor-scoped three-way merge, per-surface adapters, pre-mutation protected-content baselines, and an independent verifier that distrusts mutation receipts.

## Accomplishments

- Exact canonical blast radius: four affected claims, five artifacts, nine registered paths.
- Minimal nine-step typed plan with automatic, approval-required, and draft-only actions.
- Conflict-aware repair that never autonomously resends or rewrites a sent email.
- Independent verification across eight registered claims, thirteen targets, five protected artifacts, and six evidence versions.
- Durable retries, worker-lease recovery, dead-letter quarantine, and audited replay.
- A reproducible forty-scenario benchmark with 100% deterministic accuracy and 0% false certification on the unsafe cases.
- More than 150 runtime tests with greater than 90% coverage, plus strict web, Terraform, and container gates.

## What we learned

Agentic systems become trustworthy when autonomy is paired with explicit scope, durable state, deterministic policy, native concurrency controls, and independent evidence. The key product insight is that stale AI work is not primarily a generation problem—it is a dependency-integrity problem.

## What’s next

Expand registered packet templates beyond executive reviews, add organization-controlled manifest approval, publish live latency and cost distributions, and support additional knowledge-work surfaces without weakening the registered-lineage and independent-verification boundaries.

## Prize tracks

- Primary: **The Taskmaster** — autonomous, high-value cross-application action with minimal hand-holding.
- Secondary: **Best Architectural Design** — explicit trust boundaries, event-driven state, credential custody, failure recovery, and independent verification.
- Additional eligible targets: **Individual/Hobbyist** and **Best Multimodal UX**.

## Links to insert only after proof

- Live application: pending Cloud Run deployment
- Demo video: pending five clean live rehearsals
- Source repository: private during development; provide judge access as required
- Architecture and reproducibility instructions: included in the repository
