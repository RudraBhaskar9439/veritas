# Veritas Google Cloud foundation

The foundation provisions the production boundaries required by the verified architecture:

- least-privilege runtime service accounts;
- passwordless Cloud SQL IAM database users for API, ingress, worker, and the isolated migrator;
- Artifact Registry for immutable images;
- versioned Cloud Storage evidence snapshots;
- Pub/Sub event and dead-letter topics;
- Cloud Tasks repair queue with bounded retry policy;
- KMS and Secret Manager credential boundaries;
- PostgreSQL 16 with IAM authentication and point-in-time recovery;
- optional Cloud Run services supplied by immutable image references;
- an on-demand Cloud Run migration job with a checksum ledger and single-writer advisory lock;
- an authenticated Cloud Scheduler heartbeat that drains the transactional Drive outbox in bounded worker batches;
- payload-free retry and dead-letter log metrics with a quarantine alert policy.
- preview-specific Cloud Run and Cloud SQL growth ceilings;
- an optional project-scoped gross-cost warning budget at 20%, 50%, 80%, and 100% of the configured amount.

Terraform state configuration is intentionally environment-owned and is not committed. Initialize with a secure remote backend before applying outside an isolated preview project.

The warning budget excludes credits when calculating thresholds so operators see gross consumption before promotional offsets. It does not stop services or guarantee a spending cap. For the hackathon preview, keep the billing account in unupgraded Free Trial status and configure a console spend cap if the account exposes that feature.

Secret resources are provisioned without values. OAuth client values and the 32-byte browser-ticket key are added out-of-band so Terraform state never contains their plaintext. The API can read all browser/OAuth secrets. The worker can read only the OAuth material needed to refresh Workspace access, while both identities use the credential-encryption KMS key.

The application-session key and Drive channel-token key are also generated locally and added as secret versions out of band. Cloud Run consumes all five values through Secret Manager references. Runtime containers connect with the official Cloud SQL Python Connector and automatic IAM database authentication; there is no database-password secret.

Phase 10 operational events intentionally contain identifiers, counters, bounded error codes, and diagnostic hashes—not Workspace content, OAuth tokens, or operation payloads. The dead-letter alert points operators to the audited recovery flow; replay always creates a new operation linked to the immutable failed original.

```bash
terraform init -backend=false
terraform validate
```
