# Preview deployment runbook

This runbook begins only after the hackathon credit is redeemed and a dedicated Google Cloud project is available.

## 1. Bind the environment

Record the project ID, billing account, regional transaction-plane location, Vertex inference location, accepted Git commit, operator account, and dedicated Workspace test account. The verified preview keeps stateful services in `us-central1` and invokes Gemini 3.5 Flash through Vertex AI's `global` endpoint. Never place credential values in the repository, shell history, screenshots, Terraform variables, or Devpost text.

## 2. Bootstrap infrastructure

Use the committed Terraform in `infra/terraform` with a secure remote state backend. Review the plan before applying. The first apply creates APIs, service accounts, Artifact Registry, versioned Storage, Pub/Sub with dead letter handling, Cloud Tasks, KMS, empty Secret Manager resources, Cloud SQL, log metrics, and the dead-letter alert.

Before the first plan, apply [ADR 0014](../architecture-decisions/0014-preview-cost-containment.md): verify the Billing Overview says **Free trial account**, never **Paid account**. Pass the billing account ID, account currency, and a locally approved amount only through an uncommitted variable source to create the gross-cost warning budget. The current INR preview uses a ₹4,000 ceiling. Keep preview Cloud Run minimum instances at zero, retain the preview scaling ceilings, and enable a project spend cap in Cloud Billing if the account offers one. A normal budget alert is not a hard cap.

Acceptance evidence:

- clean Terraform plan and apply;
- service-account role list with no owner/editor grants;
- bucket versioning, KMS rotation, Cloud SQL backup/PITR, task retry, and Pub/Sub DLQ settings.
- gross-cost budget thresholds, preview instance ceilings, and the Cloud SQL disk ceiling.

## 3. Add secrets out of band

Populate the OAuth client ID/secret, 32-byte browser-ticket key, separate 32-byte application-session key, and Drive channel-token key directly in Secret Manager. API, ingress, and worker use automatic Cloud SQL IAM authentication; do not create a database-password secret. Confirm only the intended service identities can access each secret, database identity, or KMS operation.

## 4. Build immutable images

Build API, ingress, worker, and web images from the accepted commit. Push immutable digest references to Artifact Registry; do not deploy mutable `latest` tags. Terraform derives the OAuth callback from the public web URL and derives the Drive ingress notification endpoint from Cloud Run's predictable service URL. The web container reverse-proxies `/api/` to the API service so the OAuth callback and Strict application-session cookie stay on one browser origin. Record those exact values in the Google OAuth client and watch evidence.

## 5. Migrate and compose services

Grant the dedicated migrator database identity schema-owner privileges once from an administrative connection, then execute the Terraform-created `veritas-preview-migrations` Cloud Run job before starting traffic. The job takes a PostgreSQL advisory lock, verifies the immutable SHA-256 ledger, and applies SQL migrations `0001` through `0014` transactionally; checksum drift fails closed. Migrations `0012` through `0014` discover the environment's exact IAM database roles and grant only the email workflow, operation-enqueue, Gmail-thread, and unmatched-request privileges required by API, ingress, and worker. Bind runtime configuration and Secret Manager references. Keep the worker private; expose the API/web boundary and only the narrow signed Drive and authenticated Gmail notification endpoints on ingress. Confirm Cloud Scheduler invokes the worker with OIDC and that unauthenticated worker calls fail.

## 6. Configure Google OAuth and watches

Set the exact redirect URI, verified origins, consent-screen test users, and least-privilege scopes. Gmail uses `gmail.readonly` for inbound history and message reads and `gmail.compose` for unsent correction drafts; it never requests full mailbox control. Reconnect the dedicated account after any scope change, verify encrypted credential storage, create Drive and Gmail watches, and record renewal/expiry state. Confirm the Gmail API publisher can publish only to its dedicated topic, Pub/Sub push uses the dedicated `gmail-push` identity, ingress rejects a missing or wrong OIDC token, and the private worker renews Gmail watches before expiry.

## 7. Run live phase gates in order

1. OAuth and credential-custody live gate.
2. Real packet generation and manifest validation.
3. Real Drive change, snapshot, and cosmetic suppression.
4. Registered blast radius.
5. Repair planning and human approval.
6. Five real conflict-aware repair runs.
7. Independent verification and scoped certificate.
8. Worker termination, duplicate, quota, token-expiry, and partial-write recovery.
9. Hosted desktop/mobile, keyboard, refresh, and accessibility audit.
10. Five timed end-to-end demo rehearsals.

Stop on the first failed gate. Preserve logs and IDs; do not reuse a partially repaired packet as a clean rehearsal.

## 8. Freeze proof

Update the cloud proof manifest, phase reports, real evaluation metrics, image digests, architecture links, demo video, and Devpost URLs. Push one release tag only after the latest workflow, public smoke check, and all submission checklist items pass.
