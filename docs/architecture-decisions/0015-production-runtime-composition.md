# ADR 0015: Production runtime composition and passwordless Cloud SQL

## Status

Accepted for preview.

## Context

The phase implementations were independently testable, but the original container entrypoints intentionally mounted several routes with `None` dependencies. Deploying that shape would have produced healthy containers whose core packet, lineage, repair, execution, and verification endpoints failed closed as unconfigured. The browser also needed an authenticated application identity after Google OAuth, and long-lived database passwords would have weakened the credential boundary.

## Decision

The control API now composes one shared async database engine, encrypted Google credential vault, signed application-session codec, Workspace session provider, and the SQL-backed packet, lineage, repair, execution, verification, and recovery services.

Google OAuth completion issues a short-lived, HttpOnly application-session cookie containing only a signed subject and verified email. Google access and refresh tokens remain encrypted under Cloud KMS. The Workspace session provider refreshes expiring access tokens and re-encrypts the rotated envelope; raw tokens never enter the browser session.

Packet generation now uses a real HTTP Workspace writer. It creates replay-safe Google Docs named ranges, deterministic Slides text-box anchors, an unsent Gmail draft, and a Google Task. Drive application properties, deterministic RFC message IDs, and task markers prevent duplicate artifacts when a request is retried.

Cloud Run services use four distinct service accounts. API, ingress, and worker connect to PostgreSQL through the official Cloud SQL Python Connector with automatic IAM database authentication. Terraform creates `CLOUD_IAM_SERVICE_ACCOUNT` database users and grants both Cloud SQL Client and Instance User roles; no database password is generated, stored, or passed through Terraform.

Drive webhooks commit the notification and a deterministic outbox event in one database transaction. An authenticated Cloud Scheduler heartbeat invokes the private worker, which converts pending events into idempotent operations, processes a bounded batch, and leaves retries or dead letters in the durable operation ledger. The worker verifies that every stream belongs to the operation subject before loading that subject's encrypted Workspace credentials.

## Consequences

- A deployed API is no longer a health-check-only shell.
- Browser identity, Google authorization, and Google tokens have separate lifetimes and trust boundaries.
- Native packet creation is testable through real request shapes before Cloud access and repeatable against Workspace after deployment.
- Cloud SQL connections use short-lived IAM credentials and require connector egress to Google APIs and the instance connector port.
- Drive change processing is production-composed without blocking Google's webhook delivery path and recovers safely from a crash between operation enqueue and outbox acknowledgement.
- Downstream impact/planning/execution orchestration and the live Command Center read model remain explicit pre-deployment work.
