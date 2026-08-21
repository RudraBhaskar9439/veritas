# Phase 8 verification report

- Status: pre-live implementation passed locally; Linux CI and real Workspace verification pending
- Verified locally: 2026-08-21
- Local command: `node scripts/verify-phase-8.mjs`

## Pre-live gate

The Phase 8 implementation proves:

- mutation responses are never accepted as verification evidence;
- all 8 registered claims are deterministically recomputed from 6 exact evidence versions;
- all 13 registered artifact targets are independently checked;
- all 5 affected artifacts require a matching pre-repair protected-content baseline;
- both claim-level corrections in the immutable investor email are re-read from their unsent drafts, while the original sent message must remain unchanged;
- a completed run must have exactly one successful terminal record for all 9 planned steps;
- candidate claims remain explicitly excluded from coverage;
- a source update after planning marks the report stale;
- a wrong repair, missing correction, incomplete run, read failure, baseline mismatch, incomplete coverage, or stored checksum mismatch prevents certificate issuance;
- the certificate uses only the approved scoped language and binds to the report checksum, evidence snapshot IDs, content hashes, coverage counts, and repair-run ID;
- the API is unavailable unless trusted identity, snapshot storage, SQL state, Workspace sessions, and the independent read adapter are configured.

Observed local result: 130 runtime tests passed with 90.44% statement coverage; strict MyPy, Ruff, and formatting checks passed. The Phase 8-specific suite passed 14 service, stale-run, incorrect-repair, protected-region, Google read-adapter, SQL reconstruction, tamper, baseline, replay, and API tests. All earlier phase gates remain cumulative.

## Remaining live evidence

Phase 8 cannot be called production-accepted until Google credentials are available and Phase 7 completes five consecutive real Workspace repair runs. Each live run must then be independently re-read, prove all registered targets and protected regions, reject an intentionally incorrect repair, demonstrate a source-change-during-repair stale result, and issue no false certificate. Google Cloud credits are not required for the completed local implementation, but they are required for the final hosted proof.
