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

Terraform state configuration is intentionally environment-owned and is not committed. Initialize with a secure remote backend before applying outside an isolated preview project.

```bash
terraform init -backend=false
terraform validate
```

