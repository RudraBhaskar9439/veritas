# Verification strategy

Every phase has an observable deliverable, automated checks, and a hard gate. A phase is complete only when its verification command exits successfully and the evidence is recorded in the repository or CI.

## Test layers

### Contract tests

Validate JSON Schemas, API payloads, state-machine transitions, agent tool inputs, and Workspace adapter responses.

### Unit tests

Cover deterministic calculations, semantic-delta helpers, graph traversal, policies, merge logic, idempotency, certificate eligibility, and redaction.

### Integration tests

Exercise PostgreSQL, Pub/Sub-compatible event contracts, Cloud Tasks command contracts, Cloud Storage snapshots, and Google API adapters against controlled test resources.

### End-to-end tests

Create a real Decision Packet in a dedicated Google Workspace test account, trigger a change, execute repairs, and verify native artifacts.

### Failure and chaos tests

Cover duplicated delivery, worker interruption, token expiry, quota errors, model timeout, invalid structured output, concurrent human edits, source changes during execution, and partial artifact failure.

### Evaluation suite

Measure meaningful-change recall, cosmetic-change suppression, blast-radius precision and recall, repair correctness, human-edit preservation, idempotent replay, false certification, latency, and cost.

## Evidence required at every phase

- Passing local command
- Passing CI run after CI exists
- Short verification report or generated test result
- Reproduction command in the README or phase document
- No unresolved high-severity security finding on the implemented surface

## Demo integrity rule

Mocks and fixtures are permitted for unit tests. The recorded end-to-end demonstration must not use mocked Google Workspace mutations, fake Cloud Run status, fake agent events, or a pre-rendered result graph.

