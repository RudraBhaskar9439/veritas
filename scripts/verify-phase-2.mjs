import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'config/example.env',
  'docs/architecture-decisions/0002-google-credential-custody.md',
  'docs/runbooks/phase-2-google-live-gate.md',
  'docs/verification/phase-2.md',
  'services/runtime/migrations/0001_google_auth.sql',
  'services/runtime/src/veritas_runtime/auth/database.py',
  'services/runtime/src/veritas_runtime/auth/oauth.py',
  'services/runtime/src/veritas_runtime/auth/routes.py',
  'services/runtime/src/veritas_runtime/auth/service.py',
  'services/runtime/src/veritas_runtime/auth/storage.py',
  'services/runtime/src/veritas_runtime/auth/tickets.py',
  'services/runtime/src/veritas_runtime/workspace/contracts.py',
  'services/runtime/tests/test_auth_service_and_routes.py',
  'services/runtime/tests/test_credential_storage.py',
  'services/runtime/tests/test_google_oauth.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 2 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const migration = readFileSync(resolve(root, 'services/runtime/migrations/0001_google_auth.sql'), 'utf8');
for (const forbiddenColumn of ['access_token', 'refresh_token', 'client_secret']) {
  if (migration.toLowerCase().includes(forbiddenColumn)) {
    console.error(`Phase 2 verification failed: plaintext credential column ${forbiddenColumn}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 1 gate', 'node', ['scripts/verify-phase-1.mjs']]]),
  [
    'Phase 2 security tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_auth_factory.py',
      'services/runtime/tests/test_auth_service_and_routes.py',
      'services/runtime/tests/test_auth_tickets.py',
      'services/runtime/tests/test_credential_storage.py',
      'services/runtime/tests/test_google_oauth.py',
      'services/runtime/tests/test_workspace_contracts.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-2] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 2 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 2 local implementation verification passed.');
console.log('- PKCE, state, encrypted tickets, replay prevention, and denial handling are verified');
console.log('- KMS ciphertext-only credential persistence and integrity binding are verified');
console.log('- Workspace capability contracts fail closed under missing scopes');
console.log('- the real Google Cloud and Workspace live gate remains mandatory');
