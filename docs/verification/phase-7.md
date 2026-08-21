# Phase 7 verification report

- Status: pre-live implementation passed; five real Workspace repair runs pending
- Verified locally: 2026-08-21
- Accepted implementation commit: `b7e4a0af1a840044c48bfbc4351085d915705239`
- Clean Linux workflow: [verified-build run 32470875892](https://github.com/RudraBhaskar9439/veritas/actions/runs/32470875892)
- Local command: `node scripts/verify-phase-7.mjs`

## Pre-live gate

The pre-live gate proves:

- Docs reads one registered named-range span, replaces only that span, recreates its anchor, handles UTF-16 indexes, and writes against the freshly read revision;
- Slides reads one registered shape, replaces only its text, and writes against the freshly read revision;
- Tasks preserves unrelated notes and patches with the current ETag in `If-Match`;
- sent Gmail is immutable and can produce only an unsent correction draft with a deterministic retry identity;
- the three-way merge applies base-to-desired changes, recognizes already-applied repairs, and blocks overlapping human edits;
- automatic and draft-only steps execute before approval while consequential steps wait;
- after approval, the same run resumes four pending steps without repeating its five completed writes;
- a completed request replay makes zero additional mutations;
- SQL stores checksummed latest step state plus append-only transition events;
- execution remains unavailable unless trusted identity, credential, policy, and Workspace dependencies are configured.

The Phase 7-specific suite passes adapter request-shape, merge, human-edit preservation, correction-draft, ETag, SQL integrity, resume, replay, and fail-closed API tests. All earlier phase gates remain cumulative.

Observed local result: 116 runtime tests passed with 92.17% statement coverage; strict MyPy, Ruff, and formatting checks passed. The Phase 7-specific suite passed 9 tests.

## Live gate

Phase 7 is not accepted until the dedicated test account completes five consecutive end-to-end repair runs against real Google Docs, Slides, Gmail drafts, and Tasks. Each run must show exactly nine planned steps, preserve a human-authored memo paragraph byte-for-byte, create no duplicate correction draft, send no email, and either complete or expose a real overlapping-edit conflict. Mocked transports and local artifact doubles cannot satisfy this gate.
