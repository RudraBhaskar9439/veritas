# Phase 8 verification report

- Status: live independent verification and certificate path passed; live destructive negatives remain partial
- Verified locally: 2026-08-21
- Accepted implementation commit: `d5f10ae3e7d3e72469924450e5ff7f1a6ca7a92b`
- Clean Linux workflow: [verified-build run 32472264691](https://github.com/RudraBhaskar9439/veritas/actions/runs/32472264691)
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

The production verifier now re-reads real Workspace targets and has issued multiple scoped certificates. Final-release certificate `370C1A51AD95` covers 8 registered claims, 13/13 targets, 6 pinned evidence versions, and 5/5 protected projections. The UI retains explicit scoped language and no mutation receipt is treated as observed truth. Intentionally wrong repair and source-change-during-repair cases pass automated fail-closed tests; their separate live destructive demonstrations remain partial.
