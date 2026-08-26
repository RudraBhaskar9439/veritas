# Customer email to registered Google Task

## Product contract

Veritas can turn a normal inbound customer email into a conflict-safe update to one existing Google Task. It does not search the workspace for a plausible task and it does not let Gemini choose a destination. An operator first binds an allowed sender to an exact claim→task edge already present in the packet's Claim Manifest.

The customer sends to the connected company mailbox with the issued `[VX-…]` routing code in the subject. Gmail publishes a mailbox history cursor to a dedicated Pub/Sub topic. Authenticated ingress records a durable `gmail.process` operation; the worker then re-reads Gmail history and applies all authority checks before any model call.

## Authority checks

An email can reach a Task only when all of these remain true:

1. the browser session owns the decision packet;
2. the claim and Task are joined by an exact Claim Manifest edge;
3. the sender exactly matches the operator's allowlist;
4. the recipient exactly matches the connected company mailbox;
5. the subject contains the workflow's deterministic routing key;
6. the workflow is still active;
7. deterministic policy finds no sensitive or irreversible request;
8. Gemini returns a schema-valid, high-confidence reversible update; and
9. the Task's current ETag still matches the revision Veritas read.

Gemini may extract only a natural-language title and factual note. It cannot select a Task, sender, recipient, tool, or broader action. Cancellation, deletion, refunds, payments, credentials, legal action, ambiguity, low confidence, and concurrent Task edits fail closed.

## Traceability

The command center refreshes email activity every three seconds after the panel is opened. Each processed message exposes the source time, sender, outcome, bounded rationale, proposed Task title, SHA-256 body proof, content-addressed event receipt, and resulting Task revision. The original message body is not returned to the browser or written to application logs.

Task notes preserve human text and replace only a delimited Veritas-managed customer-update block. A content-addressed event marker makes retries idempotent even if the Task write succeeded immediately before a worker interruption.

## Lifecycle

- Gmail access is read-only; outgoing Gmail remains draft-only under the separate compose scope.
- Pub/Sub push uses a dedicated service account and an audience-bound OIDC token verified by ingress.
- Gmail watches are renewed by the private worker before their seven-day expiry window.
- Operators can disable a route at any time. Paused routes are rejected both by the database lookup and by the processor.
- A stale Gmail history cursor, missing OAuth scope, wrong sender, bad OIDC identity, task revision conflict, or model outage never falls back to a simulated success.

## Live acceptance test

1. Open the live incident and choose **Set up customer email**.
2. Enter the external customer's exact sender address and activate the manifest-provided Task route.
3. From that external account, send the generated example to the displayed company inbox.
4. Keep the routing code unchanged; edit the request text to a clear reversible scheduling change.
5. Verify a single natural Google Task is updated, unrelated Task text is preserved, and a matching applied receipt appears in the command center.
6. Repeat the same delivery and verify no duplicate Task mutation occurs.
7. Disable the route, send another matching email, and verify the Task does not change.

