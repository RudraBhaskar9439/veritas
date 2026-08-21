# Phase 2 Google live gate

Run this gate only in the dedicated preview Google Cloud project and Workspace test account. Unit-test fakes do not satisfy it.

## Prerequisites

1. A billing-enabled Google Cloud project ID.
2. An external or internal OAuth consent screen configured for the test account.
3. A Web application OAuth client whose redirect URI exactly matches `https://<api-host>/api/v1/auth/google/callback`.
4. Secret versions populated for the Terraform outputs `auth_secret_ids`.
5. A URL-safe Base64 ticket key created from 32 cryptographically random bytes.
6. The `0001_google_auth.sql` migration applied to the preview PostgreSQL database.
7. The API deployed with the variables shown in `config/example.env`, supplied through Secret Manager rather than committed files.

## Acceptance procedure

1. Confirm `/api/v1/integrations/google/configuration` returns `configured: true` and does not expose a client secret, KMS payload, database URL, access token, or refresh token.
2. Start authorization and confirm Google receives PKCE S256, offline access, state, the exact callback URI, and only the declared scopes.
3. Deny consent once. Confirm the browser returns with `google=denied`, no credential row is created, and the browser ticket is deleted.
4. Grant consent. Confirm the browser returns with `google=connected` and one credential row is created.
5. Inspect the row: `encrypted_payload` must not contain the access token, refresh token, client secret, or email plaintext.
6. Confirm Cloud Audit Logs contain an Encrypt call by the API service account against the `workspace-credentials` key.
7. Replay the successful callback URL. It must return HTTP 400 without contacting the Google token endpoint and without changing the credential row.
8. Restart the API and verify the encrypted credential can still be loaded and its subject, email, scopes, and key binding pass integrity validation.
9. Revoke access in the Google Account test console and record the expected invalid-credential behavior for the refresh implementation gate.

## Evidence to record

- Cloud project ID and region, but no secrets
- deployed API revision and source commit
- timestamped consent screenshot
- redacted SQL row showing ciphertext-only storage
- redacted KMS audit entry
- successful callback and rejected replay request IDs
- final CI run URL
