# Preview deployment runbook

This runbook begins only after the hackathon credit is redeemed and a dedicated Google Cloud project is available.

## 1. Bind the environment

Record the project ID, billing account, region, accepted Git commit, operator account, and dedicated Workspace test account. Never place credential values in the repository, shell history, screenshots, Terraform variables, or Devpost text.

## 2. Bootstrap infrastructure

Use the committed Terraform in `infra/terraform` with a secure remote state backend. Review the plan before applying. The first apply creates APIs, service accounts, Artifact Registry, versioned Storage, Pub/Sub with dead letter handling, Cloud Tasks, KMS, empty Secret Manager resources, Cloud SQL, log metrics, and the dead-letter alert.

Acceptance evidence:

- clean Terraform plan and apply;
- service-account role list with no owner/editor grants;
- bucket versioning, KMS rotation, Cloud SQL backup/PITR, task retry, and Pub/Sub DLQ settings.

## 3. Add secrets out of band

Populate the OAuth client ID/secret, browser-ticket key, and Drive channel-token key directly in Secret Manager. Configure database access with Cloud SQL IAM where supported. Confirm only the intended service identities can access each secret or KMS operation.

## 4. Build immutable images

Build API, ingress, worker, and web images from the accepted commit. Push immutable digest references to Artifact Registry; do not deploy mutable `latest` tags. Reapply Terraform with the four digest-pinned image references.

## 5. Migrate and compose services

Apply SQL migrations `0001` through `0008` exactly once through an auditable migration job. Bind runtime configuration and Secret Manager references. Keep ingress and worker private; expose only the intended API/web boundary. Configure Cloud Tasks and Pub/Sub calls with service identity.

## 6. Configure Google OAuth and watches

Set the exact redirect URI, verified origins, consent-screen test users, and least-privilege scopes. Connect the dedicated account, verify encrypted credential storage, create Drive watches, and record renewal/expiry state.

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

