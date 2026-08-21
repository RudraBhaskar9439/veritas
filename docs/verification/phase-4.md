# Phase 4 verification report

- Status: pre-live implementation passed; real Google Drive and Cloud Storage gate pending
- Verified locally: 2026-08-21
- Accepted implementation commit: pending
- Clean Linux workflow: pending
- Local command: `node scripts/verify-phase-4.mjs`

## Pre-live gate

The pre-live gate proves:

- Drive v3 start-page-token, watch, change-list, and channel-stop requests use validated typed responses;
- v3 change identity is derived from current fields rather than a nonexistent legacy change ID;
- watch creation is idempotent, reserves before the early `sync` race, requests a bounded lease, and fails closed;
- renewal overlaps old and new channels and stops the old channel only after the replacement syncs;
- channel tokens are HMAC-authenticated, channel/stream-bound, expiry-bound, and within Drive's length limit;
- forged, expired, unknown, mismatched, duplicate, and future-state notifications are handled safely;
- webhook deduplication and durable outbox insertion share one SQL transaction;
- manifest sources become immutable subject-and-packet-scoped registrations;
- only registered Sheets ranges and Docs named ranges are extracted;
- multi-page change processing advances the durable cursor with compare-and-swap semantics;
- repeated file entries are coalesced and removed sources become meaningful tombstones;
- Cloud Storage writes are content-addressed, CRC32C-checked, and guarded by a create-only generation precondition;
- exact duplicates, presentation-only changes, and evidence-value changes classify as duplicate, cosmetic, and meaningful respectively;
- a 4% to 9% churn change is retained as meaningful while a formatting-only change is suppressed.

Observed local result: 78 runtime tests passed with 94.88% statement coverage; strict MyPy and Ruff passed. Phase 0-3 verification remains green. Python and production web dependency audits reported no known vulnerabilities after upgrading `cryptography` to 50.0.0. Terraform validation and production container builds remain authoritative in Linux CI because Terraform is not installed in the local environment.

## Live gate

Phase 4 is not accepted until a real Drive `changes.watch` channel reaches the HTTPS ingress, survives an overlapping renewal, reads a real two-state Sheet or Doc through its native API, stores immutable objects with real Cloud Storage generation numbers, suppresses a real formatting-only edit, and emits a meaningful delta for a real evidence-value edit. No mocked notification, in-memory object store, or fixture may be presented as live evidence.
