# ADR 0007: Execute only anchor-scoped three-way repairs with native preconditions

- Status: accepted for pre-live implementation
- Date: 2026-08-21

## Context

A user can edit a Decision Packet between generation and repair. Replacing an entire document, slide, message, or task would destroy authorship and turn the agent into a dangerous synchronization script. Checking only the manifest's old artifact revision would also reject safe cases where a collaborator changed an unrelated paragraph.

Google Workspace exposes different concurrency mechanisms for each surface. Docs named ranges track their indexes as surrounding content changes and `documents.batchUpdate` accepts `writeControl.requiredRevisionId`. Slides batch updates support the same required-revision boundary. Google Tasks resources expose ETags for `If-Match` read-modify-write requests. Gmail sent messages are immutable; the supported safe action is creating an RFC 2822, base64url-encoded draft.

Official contracts:

- [Docs named ranges and guarded replacement](https://developers.google.com/workspace/docs/api/how-tos/named-ranges)
- [Docs batchUpdate write control](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate)
- [Slides batchUpdate write control](https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations/batchUpdate)
- [Gmail draft creation](https://developers.google.com/workspace/gmail/api/guides/drafts)
- [Tasks ETags and read-modify-write](https://developers.google.com/workspace/tasks/performance)

## Decision

For each approved or policy-eligible repair step, Veritas reads only the registered anchor from the latest artifact and compares three values:

1. `base`: the statement recorded in the Claim Manifest;
2. `desired`: the deterministic statement in the immutable repair plan;
3. `current`: the latest text at the registered Workspace anchor.

The merge result is deterministic:

- `current == desired`: record `already_applied` and do not write;
- `current == base`: apply the minimal anchor mutation;
- otherwise: record `conflict` and do not write.

Docs deletes and reinserts only the named-range span, recreates the range over the new UTF-16 length, and submits the revision fetched immediately before the write. Slides deletes and inserts text only in the registered shape and uses its freshly fetched revision. Tasks replaces one exact occurrence in notes and submits the current ETag in `If-Match`. A precondition race is re-read once; a second race becomes a conflict.

Gmail has no mutation or send operation in the gateway. A sent-message repair creates a correction draft with a deterministic RFC Message-ID. Before creation, the adapter searches drafts for that ID so a retry after an uncertain network result can recover the existing draft instead of duplicating it.

Runs and latest step states are persisted in SQL with checksums. Every step transition is also appended to an audit-event table. Replaying a completed execution request does not repeat external writes. An awaiting-approval run resumes the same ID after approvals arrive and skips already completed steps.

## Consequences

- Human edits outside a registered anchor survive without forcing a conflict.
- Human edits inside the exact claim boundary are never overwritten automatically.
- Workspace scope checks happen per step before any adapter call.
- The local gate proves request shapes, merge behavior, persistence, resumption, and hard negatives with mocked Workspace endpoints.
- Phase 7 remains open until five consecutive runs mutate real Docs, Slides, Gmail drafts, and Tasks in the dedicated Workspace account and preserve a real human-authored paragraph.
