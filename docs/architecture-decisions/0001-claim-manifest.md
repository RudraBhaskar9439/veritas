# ADR 0001: Capture registered lineage in a Claim Manifest

- Status: accepted
- Date: 2026-08-21

## Context

Veritas must know which evidence supports a claim and where that claim appears downstream. Inferring all relationships only after a source changes is unsafe: semantic similarity can confuse topical relevance with actual dependence, and a convincing graph can hide invented edges.

## Decision

Veritas will emit a versioned Claim Manifest whenever it creates or registers a Decision Packet. Each monitored claim records exact evidence anchors, deterministic transformations, artifact anchors, risk, freshness policy, and provenance status.

Only `registered` edges participate in automatic mutation and certification. Model-inferred `candidate` edges remain visible but require confirmation.

## Consequences

- The demo graph is generated from persisted provenance rather than UI fixtures.
- Existing documents need an onboarding and confirmation flow.
- Coverage can be stated precisely.
- Claims outside monitored coverage remain explicitly unverified.
- The architecture can fail closed when an anchor or source version is missing.

