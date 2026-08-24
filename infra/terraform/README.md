# Veritas Google Cloud foundation

The foundation provisions the production boundaries required by the verified architecture:

- least-privilege runtime service accounts;
- Artifact Registry for immutable images;
- versioned Cloud Storage evidence snapshots;
- Pub/Sub event and dead-letter topics;
- Cloud Tasks repair queue with bounded retry policy;
- KMS and Secret Manager credential boundaries;
- PostgreSQL 16 with IAM authentication and point-in-time recovery;
- optional Cloud Run services supplied by immutable image references.
- payload-free retry and dead-letter log metrics with a quarantine alert policy.
- preview-specific Cloud Run and Cloud SQL growth ceilings;
- an optional project-scoped gross-cost warning budget at 20%, 50%, 80%, and 100% of the configured amount.

Terraform state configuration is intentionally environment-owned and is not committed. Initialize with a secure remote backend before applying outside an isolated preview project.

The warning budget excludes credits when calculating thresholds so operators see gross consumption before promotional offsets. It does not stop services or guarantee a spending cap. For the hackathon preview, keep the billing account in unupgraded Free Trial status and configure a console spend cap if the account exposes that feature.

Secret resources are provisioned without values. OAuth client values and the 32-byte browser-ticket key are added out-of-band so Terraform state never contains their plaintext. The API service account alone can read these secrets and use the credential-encryption KMS key.

Phase 10 operational events intentionally contain identifiers, counters, bounded error codes, and diagnostic hashes—not Workspace content, OAuth tokens, or operation payloads. The dead-letter alert points operators to the audited recovery flow; replay always creates a new operation linked to the immutable failed original.

```bash
terraform init -backend=false
terraform validate
```
