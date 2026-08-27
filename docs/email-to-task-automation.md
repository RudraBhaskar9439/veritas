# Customer Gmail conversation to registered Google Task

## Product contract

Veritas turns an ordinary customer reply into a conflict-safe update to one existing Google Task.
The customer never sees a routing code and does not need to know that Veritas exists. An operator
first authorizes a sender and chooses an exact claim→Google Task edge already registered in the
packet's Claim Manifest.

The operator then starts a normal company-to-customer Gmail conversation. Veritas stores the
returned Gmail thread ID as the private authority binding. A later reply can reach the Task only
through that exact thread, sender, recipient, and manifest edge. Gemini interprets the request but
cannot choose a destination.

Clear reversible requests can update the Task automatically. Decision reversals, sensitive
actions, low-confidence interpretations, and policy flags enter an authenticated human authority
boundary. The operator sees the proposed title and note, then either approves the exact bounded
update or rejects it. Approval re-reads the live Task, uses its ETag as a write precondition,
preserves human notes, and records the resulting Task revision. Rejection performs no Workspace
mutation.

## Authority checks

A reply can reach a Task only when all of these remain true:

1. the browser session owns the decision packet;
2. the claim and Task are joined by an exact Claim Manifest edge;
3. the Gmail thread is registered to that workflow;
4. the sender exactly matches the authorized customer;
5. the recipient exactly matches the connected company mailbox;
6. the workflow is still active;
7. deterministic policy finds no sensitive or irreversible request;
8. Gemini returns a schema-valid, high-confidence reversible update; and
9. the Task's current ETag still matches the revision Veritas read.

New mail from an authorized sender but outside a registered thread is stored as a body-hash-only
unmatched request. It never changes a Task automatically. An operator may bind that thread to one
of the exact sender-authorized manifest workflows; subsequent replies then follow the normal path.

## Conversation creation and idempotency

The API uses the existing bounded Gmail compose permission to send the opening company email. The
message has a deterministic RFC Message-ID. Before sending, Veritas searches the connected mailbox
for that Message-ID, so retrying conversation setup reuses the original Gmail message and thread
instead of creating another customer email.

The opening subject and body are ordinary customer-facing prose. Internal workflow identifiers
remain server-side and appear only in audit storage.

## Traceability

The command center refreshes every three seconds. Each processed reply exposes the source time,
sender, outcome, bounded rationale, proposed Task title, SHA-256 body proof, content-addressed event
receipt, and resulting Task revision. The raw inbound body is not returned to the browser or
written to application logs.

An escalated request records a separate human-review receipt bound to the immutable inbound
receipt, authenticated reviewer, approve/reject decision, reason, timestamp, outcome, and resulting
Task revision. Review requests are idempotent. A concurrent Task edit fails closed and returns the
request to the pending authority boundary without overwriting the human change.

Task notes preserve human text and replace only a delimited Veritas-managed customer-update block.
A content-addressed event marker makes retries idempotent even if the Task write succeeded
immediately before a worker interruption.

## Live acceptance test

1. Open the live incident and choose **Set up customer email**.
2. Enter the customer's exact address and register the manifest-provided Task.
3. Choose **Send opening email & bind thread** and confirm the normal email appears in Sent.
4. From the authorized customer account, press Reply and request a clear reversible task change.
5. Verify one natural Google Task updates, unrelated Task text survives, and an applied receipt
   appears in the command center.
6. Send a decision reversal, approve the exact proposed update in the command center, and verify
   the Task changes once with a separate authenticated review receipt.
7. Start a separate new email from the same customer and verify it appears under **Unmatched
   requests** without changing a Task.
8. Bind that thread, reply once more, and verify the exact same authority checks apply.
9. Disable the automation, send another reply, and verify the Task does not change.
