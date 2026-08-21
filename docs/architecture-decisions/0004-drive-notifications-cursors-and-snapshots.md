# ADR 0004: Treat Drive notifications as wake-up signals, not evidence

- Status: accepted for pre-live implementation
- Date: 2026-08-21

## Context

Google Drive push notifications have empty bodies. Their message numbers increase but are not sequential, notification channels expire, replacement channels overlap, and the initial `sync` notification can arrive before the watch request returns. A webhook therefore cannot prove what changed, and delivery order cannot be the source of truth.

Veritas must also distinguish a formatting edit from a decision-changing evidence edit without losing the exact source state used for later repair and certification.

## Decision

Veritas uses four separate integrity layers:

1. **Authenticated wake-up:** each channel is reserved before the Drive watch call and receives a short HMAC-signed token bound to its channel, stream, and expiry. Webhooks are deduplicated by `(channel_id, message_number)` and committed with an outbox record in the same SQL transaction.
2. **Durable Drive cursor:** notifications only wake a worker. The worker reads `changes.list` from the persisted page token, follows every page, and transactionally advances the cursor. Overlapping channels share one stream cursor, so duplicate wake-ups do not duplicate evidence events.
3. **Immutable evidence:** registered Sheets ranges and Docs named ranges are read through their native APIs. Exact extracted evidence plus presentation metadata is canonicalized and written to a content-addressed Cloud Storage object with `if_generation_match=0` and CRC32C validation. Existing objects are accepted only when their recorded SHA-256 matches.
4. **Conservative semantic delta:** the exact-content hash covers identity, Workspace version, evidence, and presentation. The semantic hash covers the resource, MIME type, and registered evidence values only. Equal exact hashes are duplicates; unequal exact hashes with equal semantic hashes are cosmetic; changed evidence hashes are meaningful. Deletion becomes a semantic tombstone.

Watch channels request six-day leases, below Drive's documented seven-day maximum for `changes`. Renewal creates the replacement first, waits for its authenticated `sync`, and only then stops the old channel. Source registrations and snapshots are scoped by Workspace subject, packet, and source ID; a registered identity cannot be rebound to another Drive resource.

Current protocol decisions follow the official [Drive push notification guide](https://developers.google.com/workspace/drive/api/guides/push), [Drive v3 Change resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes), [changes.list contract](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list), and [Cloud Storage generation preconditions](https://cloud.google.com/storage/docs/request-preconditions).

## Consequences

- Webhook delivery is fast and contains no business processing.
- A forged, expired, unknown, or resource-mismatched notification fails closed.
- A crash after object creation but before cursor commit is safe because the object write is content-addressed and create-only.
- Concurrent workers may perform duplicate reads, but only one cursor compare-and-swap can commit.
- Cosmetic suppression applies only to explicitly registered evidence anchors; unregistered document content is outside certification coverage.
- Real watch delivery, native API extraction, Cloud Storage generations, and renewal still require the live Google gate.
