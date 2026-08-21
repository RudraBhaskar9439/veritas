import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0010-durable-operation-recovery.md',
  'docs/runbooks/operations-recovery.md',
  'docs/verification/phase-10.md',
  'services/runtime/migrations/0008_operational_reliability.sql',
  'services/runtime/src/veritas_runtime/operations/database.py',
  'services/runtime/src/veritas_runtime/operations/models.py',
  'services/runtime/src/veritas_runtime/operations/routes.py',
  'services/runtime/src/veritas_runtime/operations/service.py',
  'services/runtime/src/veritas_runtime/operations/telemetry.py',
  'services/runtime/tests/test_operations_database.py',
  'services/runtime/tests/test_operations_routes.py',
  'services/runtime/tests/test_operations_service.py',
  'services/runtime/tests/test_security.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 10 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const migration = readFileSync(
  resolve(root, 'services/runtime/migrations/0008_operational_reliability.sql'),
  'utf8'
).toLowerCase();
for (const contract of [
  'create table operations',
  'create table operation_events',
  "'dead_letter'",
  'lease_expires_at',
  'idempotency_key varchar(512) not null unique'
]) {
  if (!migration.includes(contract)) {
    console.error(`Phase 10 verification failed: migration lacks ${contract}`);
    process.exit(1);
  }
}

const service = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/operations/service.py'),
  'utf8'
);
for (const contract of [
  'operation.leases_recovered',
  'operation.retry_scheduled',
  'operation.dead_lettered',
  'diagnostic_fingerprint',
  'unsupported_operation_kind'
]) {
  if (!service.includes(contract)) {
    console.error(`Phase 10 verification failed: service lacks ${contract}`);
    process.exit(1);
  }
}
for (const forbidden of ['payload=operation.payload', 'error_message=str(error)']) {
  if (service.includes(forbidden)) {
    console.error(`Phase 10 verification failed: telemetry exposes ${forbidden}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 9 gate', 'node', ['scripts/verify-phase-9.mjs']]]),
  ['Python lint', 'uv', ['run', 'ruff', 'check', '.']],
  ['Python format', 'uv', ['run', 'ruff', 'format', '--check', '.']],
  ['Python types', 'uv', ['run', 'mypy']],
  [
    'Phase 10 failure-injection and recovery tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_operations_service.py',
      'services/runtime/tests/test_operations_database.py',
      'services/runtime/tests/test_operations_routes.py',
      'services/runtime/tests/test_security.py',
      'services/runtime/tests/test_health.py',
      'services/runtime/tests/test_service_roles.py'
    ]
  ],
  ...(process.argv.includes('--ci')
    ? [['Terraform formatting', 'terraform', ['-chdir=infra/terraform', 'fmt', '-check', '-recursive']]]
    : []),
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-10] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 10 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 10 credit-independent reliability verification passed.');
console.log('- duplicate delivery, bounded retry, dead letters, replay, and lease recovery are proven');
console.log('- operational events exclude work payloads and raw exception text');
console.log('- HTTP and infrastructure security contracts fail closed');
console.log('- live Cloud failure injection remains mandatory after deployment');
