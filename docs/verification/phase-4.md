# Phase 4 verification report

- Status: live Drive change and immutable Storage proof passed; renewal/cosmetic recording remains partial
- Verified locally: 2026-08-21
- Accepted implementation commit: `c8bf0add5472d7581fc447de23d87822f451ecf6`
- Clean Linux workflow: [verified-build run 32468355683](https://github.com/RudraBhaskar9439/veritas/actions/runs/32468355683)
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

On 2026-08-26, a real `Metrics!B17` change reached the HTTPS ingress through the active Drive watch, was read through the Sheets API, and produced an immutable snapshot, semantic hashes, and append-only receipts in the versioned Cloud Storage bucket. Repeated real value edits were classified as meaningful and drove scoped incidents. Channel renewal and formatting-only suppression remain strongly automated but have not both been separately recorded as live demonstrations, so that narrower proof remains partial rather than overstated.
