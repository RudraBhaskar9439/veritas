# ADR 0002: Keep Google credentials inside a narrow server-side custody boundary

- Status: accepted
- Date: 2026-08-21

## Context

Veritas needs offline access because evidence changes and repairs happen when the user is not in the browser. Refresh tokens therefore become high-value credentials. Browser-held tokens, plaintext database columns, reusable OAuth state, or broad Workspace scopes would create an unacceptable blast radius.

Google recommends the authorization-code flow for backend applications, `state` validation for CSRF protection, offline access for background work, and encryption of stored multi-user tokens. Cloud KMS limits direct Encrypt/Decrypt input to 64 KiB, which safely contains the small versioned token envelope used here.

References:

- [OAuth 2.0 for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google OAuth security best practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)
- [Cloud KMS envelope-encryption guidance](https://cloud.google.com/kms/docs/envelope-encryption)

## Decision

- Use a server-side authorization-code flow with PKCE S256, exact redirect URI, offline access, granular consent, and an unpredictable `state`.
- Put the state, PKCE verifier, issue time, and safe relative return path in an AES-GCM-encrypted, HttpOnly, SameSite=Lax browser ticket lasting ten minutes.
- Persist only a SHA-256 state digest and atomically consume it before exchanging the code. A callback can succeed, fail, or be denied only once.
- Verify the Google account through the OpenID user-info endpoint and require a verified email.
- Require every declared capability scope. Missing grants fail closed.
- Encrypt the versioned token envelope with the non-exportable Cloud KMS credential key before writing it to PostgreSQL. The database never receives plaintext access or refresh tokens.
- Bind the subject, email, scopes, and KMS key resource inside and outside the encrypted envelope and reject mismatches to detect record swapping or corruption.
- Keep KMS decrypt and OAuth secrets on the control API service account. Workers will use a later internal credential-broker boundary instead of receiving refresh tokens directly.
- Request `drive.file` and `gmail.compose`; never request full Drive or full Gmail mailbox access for the canonical product loop.

## Consequences

- A compromised browser cannot read Google tokens.
- A database-only compromise yields ciphertext and non-secret metadata.
- A replayed or expired callback fails before reaching Google.
- The control API is a deliberate high-trust boundary and requires strong service-to-service controls before repair workers are enabled.
- Monday's live gate must prove real consent, KMS encryption, SQL persistence, denial handling, and replay rejection in the preview project.
