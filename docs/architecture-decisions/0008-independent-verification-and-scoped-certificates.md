# ADR 0008: Verify independently and certify only complete registered coverage

- Status: accepted for pre-live implementation
- Date: 2026-08-21

## Context

A repair agent cannot be allowed to certify its own success from mutation responses. A successful HTTP response proves only that an API accepted a request; it does not prove that every registered claim now matches its causal evidence, that another source did not change during repair, or that a collaborator's surrounding work survived.

Certification must also remain narrower than universal fact checking. Veritas knows the claims, sources, transformations, artifacts, and anchors explicitly registered in a versioned Claim Manifest. Model-inferred candidate lineage and unregistered prose are outside that claim-accuracy boundary.

The canonical packet contains an immutable sent Gmail message. Veritas must not alter or resend it autonomously. Its current registered resolution is therefore a separately read, unsent correction draft, while the independent verifier also proves that the historical original remains unchanged.

## Decision

Phase 8 introduces a read-only verification path separated from the Workspace mutation gateway. It does not accept execution response bodies or mutation receipts as artifact truth. After a repair run, it independently re-reads Google Docs named ranges, Slides shapes, the original Gmail message and correction drafts, and Google Task notes.

Before the first mutation, execution invokes a protected-region baseline collaborator. For every affected artifact, it hashes the content outside the exact affected registered anchors and persists that baseline with the repair run. Baseline capture is idempotent and immutable. After repair, the independent reader recomputes the same projection. A missing baseline, different anchor set, changed resource identity, or changed protected-content hash prevents certification.

The verifier then applies these deterministic gates:

1. The run must contain exactly one successful terminal record for every repair-plan step.
2. The latest immutable snapshot for every registered source must match the causal version selected by the repair plan or the unchanged manifest version. Any newer source marks the result `stale`.
3. Every registered claim is recomputed with its recorded transformation name, version, parameters, and exact source snapshots.
4. Every registered target is independently read and compared with that recomputed statement.
5. An immutable Gmail target passes only when its original remains unchanged and its execution-linked correction draft contains the recomputed claim.
6. Every affected artifact's protected-region hash must match its sealed pre-repair baseline.
7. Coverage must equal all registered claims, all their targets, and all affected protected artifacts. Candidate claims are counted as excluded and cannot silently enter the certificate.

Checks record hashes of expected and observed statements, not sensitive text. Reports, protected baselines, and certificates are stored with canonical SHA-256 checksums. A certificate is created in the same persistence boundary only for a `verified` report and binds to that report's checksum. A replay returns the immutable point-in-time result; a new request is required for a new verification timestamp.

The only permitted certificate statement is:

> All monitored claims in this Decision Packet are consistent with their registered evidence versions as of the stated timestamp.

The certificate includes exact coverage counts, all evidence snapshot IDs and content hashes, the repair-run ID, the verification-report checksum, and the number of independently verified correction drafts. It makes no claim about candidate lineage, unregistered prose, universal truth, or future source versions.

## Consequences

- A deliberately incorrect repair produces a rejected report and no certificate.
- A source update during repair produces a stale report and no certificate, even if artifacts match the earlier plan.
- Missing steps, missing correction drafts, altered immutable originals, incomplete coverage, and changed human-authored regions all fail closed.
- Google reads can fail without accidentally issuing a certificate; read errors become failed checks.
- SQL corruption of a report, baseline, or certificate is detected before reuse.
- Phase 8's local gate proves the independent algorithms, adapter request shapes, SQL reconstruction, negative cases, and fail-closed API. Real Workspace certification remains pending until the Phase 7 live runs can execute with the dedicated Google account.
