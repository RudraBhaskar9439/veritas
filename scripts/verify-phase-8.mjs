import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0008-independent-verification-and-scoped-certificates.md',
  'docs/verification/phase-8.md',
  'services/runtime/migrations/0007_independent_verification.sql',
  'services/runtime/src/veritas_runtime/verification/database.py',
  'services/runtime/src/veritas_runtime/verification/google.py',
  'services/runtime/src/veritas_runtime/verification/models.py',
  'services/runtime/src/veritas_runtime/verification/routes.py',
  'services/runtime/src/veritas_runtime/verification/service.py',
  'services/runtime/tests/test_google_verification_gateway.py',
  'services/runtime/tests/test_verification_baselines_routes.py',
  'services/runtime/tests/test_verification_database.py',
  'services/runtime/tests/test_verification_service.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 8 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const models = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/verification/models.py'),
  'utf8'
);
if (
  !models.includes('All monitored claims in this Decision Packet') ||
  !models.includes('evidence versions as of the stated timestamp.')
) {
  console.error('Phase 8 verification failed: approved scoped certificate language changed');
  process.exit(1);
}

const gateway = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/verification/google.py'),
  'utf8'
);
for (const forbidden of ['self._client.post(', 'self._client.patch(', 'self._client.delete(', '/send']) {
  if (gateway.includes(forbidden)) {
    console.error(`Phase 8 verification failed: read-only gateway contains ${forbidden}`);
    process.exit(1);
  }
}

const migration = readFileSync(
  resolve(root, 'services/runtime/migrations/0007_independent_verification.sql'),
  'utf8'
).toLowerCase();
for (const contract of [
  'create table artifact_protection_baselines',
  'create table verification_reports',
  'create table integrity_certificates',
  'report_id varchar(255) not null unique'
]) {
  if (!migration.includes(contract)) {
    console.error(`Phase 8 verification failed: migration lacks ${contract}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 7 gate', 'node', ['scripts/verify-phase-7.mjs']]]),
  [
    'Phase 8 independent verification tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_google_verification_gateway.py',
      'services/runtime/tests/test_verification_baselines_routes.py',
      'services/runtime/tests/test_verification_database.py',
      'services/runtime/tests/test_verification_service.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-8] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 8 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 8 pre-live independent verification passed.');
console.log('- mutation receipts are never trusted as artifact truth');
console.log('- wrong, stale, incomplete, or human-altering repairs cannot certify');
console.log('- all registered claims, targets, sources, and protected artifacts are covered');
console.log('- real Workspace verification remains mandatory after credentials arrive');
