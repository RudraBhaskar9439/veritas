# ADR 0011: A checksummed benchmark that executes production decisions

- Status: accepted for deterministic evaluation
- Date: 2026-08-21

## Context

A polished canonical demo can hide brittleness. Conversely, a benchmark can be meaningless if it merely compares an expected field with a pre-filled actual field. Veritas needs a compact evaluation that judges can reproduce and that measures the safety-critical deterministic boundaries before Google Cloud credentials exist.

## Decision

Phase 11 publishes forty checksummed scenarios in five balanced strata: semantic delta classification, registered lineage, repair policy, three-way merge, and certificate eligibility. The harness imports and calls the same production functions used by the runtime.

The committed result is deterministic and contains no wall-clock timestamp. Its dataset SHA-256 binds the metrics to the exact scenarios. A verification run also measures local execution time against a generous one-second budget but does not commit hardware-dependent latency as a product claim.

The hard thresholds are:

- 40 unique scenarios;
- 100% overall deterministic accuracy;
- 100% meaningful-change recall and cosmetic-change suppression;
- 100% registered-lineage precision and recall;
- 100% repair-decision accuracy;
- 100% human-edit conflict detection;
- 0% false certification across the unsafe certificate cases;
- less than 1,000 ms for the external-API-free offline suite.

Offline external API calls and external API cost must remain zero. Live Google Cloud cost and end-to-end latency are explicitly `pending`, not estimated or simulated.

## Consequences

- Changes to safety-critical deterministic behavior cannot silently alter the published score.
- Dataset edits invalidate the committed checksum and require an intentional metrics update.
- The evaluation remains small enough to run on every commit.
- The perfect offline score is narrow: it does not prove model quality, Google API availability, live Workspace correctness, or production cost.
- After deployment, the suite must be supplemented with real Workspace scenarios and published live latency/cost distributions.

