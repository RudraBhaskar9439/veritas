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

Veritas is deployed in Google Cloud project `project-c0f0f832-e02b-4eac-ae2` at [the public Command Center](https://veritas-preview-web-602044424209.us-central1.run.app/). The accepted application release commit is `39b337f`; Cloud Build produced immutable runtime and web images, four Cloud Run services serve those digests, and the production migration job is bound to the same runtime image. Real Google Workspace runs now generate native Sheets, Docs, Slides, Gmail drafts, and human-readable Tasks; a real Sheet edit autonomously drives impact analysis, guarded repair, two human approvals, in-place task updates, independent re-read, and a scoped certificate. Ambiguous customer email requests now stop at an authenticated human authority boundary with a proposed Task change, ETag protection, explicit approve/reject controls, and a separate review receipt. Live Gemini outages have also exercised bounded retry, dead-letter quarantine, and audited replay. The deterministic forty-scenario benchmark and the complete local verification suite remain green. The repository intentionally reports the five-consecutive-run proof, exact live cost and model usage, recorded video, and final Devpost submission as unfinished until their evidence exists.

See:

- [Product contract](docs/product-contract.md)
- [Canonical demo scenario](docs/demo-scenario.md)
- [Phase gates](docs/phases.md)
- [Verification strategy](docs/verification-strategy.md)
- [Claim Manifest decision record](docs/architecture-decisions/0001-claim-manifest.md)
- [Thread-bound customer email routing](docs/architecture-decisions/0017-thread-bound-customer-conversations.md)
- [Customer email → Google Task contract](docs/email-to-task-automation.md)
- [Live production proof](docs/submission/live-proof-report.md)
- [Public Command Center](https://veritas-preview-web-602044424209.us-central1.run.app/)

## Judge quick start — no account required

1. Open the [public Command Center](https://veritas-preview-web-602044424209.us-central1.run.app/).
2. Select **Open offline judge demo**. The interface labels this data as a demonstration and never substitutes it for live data silently.
3. Move through **Incident**, **Blast radius**, **Repair plan**, **Execution**, **Verification**, and **Proof ledger** to inspect the complete registered 4% → 9% scenario.
4. Compare the walkthrough with the [live production proof](docs/submission/live-proof-report.md) and [judge testing guide](docs/submission/judge-testing.md). The recorded submission video is the proof of an unedited run against real Google Workspace resources.

The public walkthrough does not require Google credentials and cannot mutate the entrant's Workspace. The authenticated live path is intentionally subject-scoped because it can read and update real Docs, Slides, Gmail drafts, and Tasks.

## Local spin-up

### Prerequisites

- Git
- Node.js 22 and Corepack
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose (only needed for the containerized preview)

### Install and verify from source

```bash
git clone https://github.com/RudraBhaskar9439/veritas.git
cd veritas
corepack enable
corepack prepare pnpm@11.8.0 --activate
pnpm install --frozen-lockfile
uv sync --all-packages --dev --frozen
node scripts/verify-phase-12.mjs
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
docker build -f services/runtime/Dockerfile -t veritas-runtime:local .
docker build -f apps/web/Dockerfile -t veritas-web:local .
```

These commands run every cumulative contract gate: Python lint, formatting, typing, tests with at least 90% coverage, web lint/type/tests/build, Terraform validation, both container builds, the forty-scenario evaluation, and five deterministic demo rehearsals.

### Run the browser experience locally

```bash
pnpm --filter @veritas/web dev
```

Open <http://127.0.0.1:5173/> and choose **Open offline judge demo**. This is the fastest reproducible UI path and does not require Cloud or Workspace credentials.

### Run the containerized preview

```bash
docker compose up --build
```

Open <http://127.0.0.1:3000/>. Liveness is available at <http://127.0.0.1:8080/health/live>. The local services start without real OAuth secrets, so `/health/ready` intentionally returns `503 not_ready` and live Google actions remain unavailable until the environment is configured.

Stop the preview with `docker compose down`. Add `--volumes` only when you deliberately want to delete the local PostgreSQL volume.

## Configure a real Google Workspace environment

1. Copy [`config/example.env`](config/example.env) to an untracked local environment file and replace every `YOUR_...` placeholder. Never commit the resulting file.
2. Create a Google OAuth web client with the exact callback URL, add the application origin, configure consent-screen test users, and enable Drive, Sheets, Docs, Slides, Gmail, and Tasks APIs.
3. Use only the declared least-privilege scopes. Veritas reads inbound Gmail messages, creates unsent correction drafts, and updates only manifest-bound Tasks; it has no email-send endpoint.
4. Provision the Google Cloud resources in [`infra/terraform`](infra/terraform) and add OAuth and application keys directly to Secret Manager, following the [Cloud deployment runbook](docs/runbooks/cloud-deployment.md).
5. Execute the Terraform-created `veritas-preview-migrations` Cloud Run job before routing traffic.
6. Connect the dedicated Workspace account from the Command Center, generate a decision packet, then change the registered Sheet cell. The authenticated Drive event advances the agent automatically; decision-changing consequences pause for explicit approval.

Google credentials, database passwords, billing identifiers, and secret values are deliberately absent from this repository.

## Cloud deployment

The committed Terraform and Cloud Build definitions reproduce the deployed topology. A concise release sequence is:

```bash
gcloud builds submit --config cloudbuild.preview.yaml --substitutions=_IMAGE_TAG=YOUR_COMMIT_SHA .
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform plan -var='project_id=YOUR_PROJECT_ID'
terraform -chdir=infra/terraform apply -var='project_id=YOUR_PROJECT_ID'
```

Use immutable Artifact Registry digests in `service_images`, review every Terraform plan, run migrations before traffic, and then verify `/health/ready`. Full secret, OAuth, IAM, watch-renewal, budget, and rollout instructions are in the [Cloud deployment runbook](docs/runbooks/cloud-deployment.md).

## Submission evidence

- [Architecture diagram](docs/submission/veritas-architecture.svg)
- [Judge testing guide](docs/submission/judge-testing.md)
- [Implementation and reuse disclosures](docs/submission/disclosures.md)
- [Cloud proof manifest](docs/submission/cloud-proof-manifest.json)
- [Claim-to-evidence matrix](docs/submission/claim-evidence-matrix.md)
- [Four-minute recording runbook](docs/submission/recording-runbook.md)
- [Devpost description draft](docs/submission/devpost-draft.md)

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
