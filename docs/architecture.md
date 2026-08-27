# Veritas production architecture

```mermaid
flowchart LR
  subgraph Workspace["Google Workspace — user-owned truth surfaces"]
    Sheet["Sheets evidence"]
    Docs["Docs + named ranges"]
    Slides["Slides + registered shapes"]
    Gmail["Gmail original + correction draft"]
    Tasks["Google Tasks"]
  end

  subgraph Cloud["Google Cloud — regional transaction plane + global Vertex inference"]
    API["Cloud Run API\nauth + subject-scoped read model"]
    Ingress["Cloud Run ingress\nchannel validation + dedupe"]
    Snapshots["Cloud Storage\nimmutable evidence snapshots"]
    Scheduler["Cloud Scheduler\nauthenticated heartbeat"]
    Worker["Private Cloud Run worker\ndeterministic agent loop"]
    Gemini["Gemini 3.5 Flash on Vertex AI global\nbounded structured safety review"]
    Database["Cloud SQL PostgreSQL\noutbox + manifests + journals + leases + audits"]
    KMS["KMS + Secret Manager\ncredential custody"]
    Verify["Independent read-only verifier"]
    Logs["Cloud Logging + Monitoring\npayload-free operational events"]
  end

  UI["Command Center\nincident evidence room"]

  Sheet -->|"Drive notification"| Ingress
  Ingress -->|"transactional outbox"| Database
  Scheduler -->|"OIDC invocation"| Worker
  Database -->|"leased operation"| Worker
  Worker -->|"refetch exact source"| Sheet
  Worker --> Snapshots
  Worker -->|"schema-bound review"| Gemini
  Gemini -->|"proceed or escalate receipt"| Worker
  Worker <-->|"registered Claim Manifest"| Database
  Worker -->|"minimal guarded writes"| Docs
  Worker -->|"minimal guarded writes"| Slides
  Worker -->|"unsent correction only"| Gmail
  Worker -->|"ETag-guarded update"| Tasks
  KMS --> Worker
  KMS --> Ingress
  Docs --> Verify
  Slides --> Verify
  Gmail --> Verify
  Tasks --> Verify
  Snapshots --> Verify
  Database --> Verify
  Verify -->|"checksummed scoped certificate"| Database
  UI -->|"same-origin /api proxy"| API
  API <-->|"checksummed records"| Database
  KMS --> API
  Worker --> Logs
  API --> Logs
  Ingress --> Logs
  Verify --> Logs
```

## Why the architecture matters

The worker is not a brittle chain of browser calls. Gemini 3.5 Flash, accessed through Google's Gen AI SDK on Vertex AI's supported global inference endpoint, reviews the already-scoped impact and plan and may force human escalation. The stateful transaction plane remains in `us-central1`. Durable deterministic code still owns evidence versions, semantic classification, registered graph traversal, policy, native API preconditions, idempotency, leases, checksums, and certificate eligibility. The model cannot invent scope or authorize itself. Each meaningful change advances automatically through the complete lifecycle under one correlation root.

The mutation path and verification path are separate. A successful write response is never accepted as proof. The verifier independently re-reads every registered target and compares protected-content hashes captured before mutation.

## Failure boundaries

```mermaid
stateDiagram-v2
  [*] --> Queued
  Queued --> Running: atomic worker lease
  Running --> Succeeded: handler + journal complete
  Running --> RetryWait: bounded retryable failure
  RetryWait --> Running: deterministic backoff elapsed
  Running --> DeadLetter: permanent or exhausted failure
  Running --> Queued: expired lease recovered
  DeadLetter --> Queued: audited operator replay creates linked operation
  Succeeded --> [*]
```

Human edit conflicts and source movement do not silently retry into an overwrite. They stop the run, prevent certification, and surface the exact registered boundary requiring review.
