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

  subgraph Cloud["Google Cloud — single-region transactional runtime"]
    Ingress["Cloud Run ingress\nchannel validation + dedupe"]
    Events["Pub/Sub\nordered change events"]
    Snapshots["Cloud Storage\nimmutable evidence snapshots"]
    Worker["Cloud Run worker\nGemini interpretation + deterministic tools"]
    Queue["Cloud Tasks\nbounded delivery retries"]
    Database["Cloud SQL PostgreSQL\nmanifests + journals + leases + audits"]
    KMS["KMS + Secret Manager\ncredential custody"]
    Verify["Independent read-only verifier"]
    Logs["Cloud Logging + Monitoring\npayload-free operational events"]
  end

  UI["Command Center\nincident evidence room"]

  Sheet -->|"Drive notification"| Ingress
  Ingress --> Events
  Events --> Worker
  Worker -->|"refetch exact source"| Sheet
  Worker --> Snapshots
  Worker <-->|"registered Claim Manifest"| Database
  Worker -->|"typed repair commands"| Queue
  Queue --> Worker
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
  Database --> UI
  Worker --> Logs
  Ingress --> Logs
  Verify --> Logs
```

## Why the architecture matters

The model is not the transaction coordinator. Gemini may interpret whether a source change is meaningful and help propose a repair, but deterministic code owns evidence versions, registered graph traversal, policy, native API preconditions, idempotency, leases, checksums, and certificate eligibility.

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

