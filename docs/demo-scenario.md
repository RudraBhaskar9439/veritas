# Canonical demo scenario

## Story

The Q3 Executive Review was generated when customer churn was 4%. The resulting memo, presentation, investor email, retention plan, and acquisition task contain claims derived from that value. The CFO later adds an original paragraph to the memo.

The source Sheet is then changed from 4% to 9%.

## Expected detection

- The Drive notification is accepted and deduplicated.
- The changed Sheet is refetched and snapshotted.
- The delta is classified as a material numeric change.
- Formatting-only and unrelated cells are ignored.

## Expected blast radius

- 4 affected monitored claims
- 5 affected artifacts
- 4 unaffected monitored claims
- 0 candidate edges used for automatic repair or certification

## Expected policy decisions

- Factual corrections in editable Docs and Slides may execute automatically.
- The acquisition recommendation is decision-changing and requires approval.
- The previously sent investor email is immutable; Veritas creates a correction draft.
- Any overlapping human edit creates a conflict rather than an overwrite.

## Expected repair

- Board memo claims are patched without replacing the CFO paragraph.
- Executive deck values, conclusion, and recommendation are patched at registered anchors.
- A correction email draft is created and linked to the incident.
- The retention plan is updated.
- The acquisition task remains pending until approval, then is changed or cancelled according to the approved plan.

## Expected verification

- Every monitored claim resolves to the new evidence version.
- Numeric calculations match deterministic functions.
- No old 4% assertion remains at a registered anchor.
- Unaffected claims remain unchanged.
- Human-authored protected regions remain byte-for-byte equivalent.
- All repair steps have terminal states.
- A certificate is issued only after the final check passes.

## Required negative demonstrations

1. A formatting-only Sheet edit produces no repair incident.
2. A deliberately incorrect repair is rejected by the verifier.
3. A duplicate event does not create duplicate mutations.
4. A worker interrupted after one artifact resumes without repeating completed writes.
5. A source change during repair marks the run stale and prevents certification.

