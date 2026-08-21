import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0007-anchor-scoped-three-way-workspace-repair.md',
  'docs/verification/phase-7.md',
  'services/runtime/migrations/0006_repair_execution.sql',
  'services/runtime/src/veritas_runtime/execution/database.py',
  'services/runtime/src/veritas_runtime/execution/google.py',
  'services/runtime/src/veritas_runtime/execution/merge.py',
  'services/runtime/src/veritas_runtime/execution/models.py',
  'services/runtime/src/veritas_runtime/execution/routes.py',
  'services/runtime/src/veritas_runtime/execution/service.py',
  'services/runtime/tests/test_execution_database_routes.py',
  'services/runtime/tests/test_execution_merge.py',
  'services/runtime/tests/test_execution_service.py',
  'services/runtime/tests/test_google_execution_gateway.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 7 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const gateway = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/execution/google.py'),
  'utf8'
);
for (const contract of [
  'requiredRevisionId',
  'If-Match',
  'CREATE_CORRECTION_DRAFT',
  'rfc822msgid'
]) {
  if (!gateway.includes(contract)) {
    console.error(`Phase 7 verification failed: Workspace gateway lacks ${contract}`);
    process.exit(1);
  }
}
if (gateway.includes('/send')) {
  console.error('Phase 7 verification failed: Gmail gateway contains a send endpoint');
  process.exit(1);
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 6 gate', 'node', ['scripts/verify-phase-6.mjs']]]),
  [
    'Phase 7 conflict-aware execution tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_execution_database_routes.py',
      'services/runtime/tests/test_execution_merge.py',
      'services/runtime/tests/test_execution_service.py',
      'services/runtime/tests/test_google_execution_gateway.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-7] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 7 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 7 pre-live execution verification passed.');
console.log('- registered anchors use deterministic three-way merge and native preconditions');
console.log('- unrelated human edits survive while overlapping edits become conflicts');
console.log('- sent Gmail produces only an idempotent, unsent correction draft');
console.log('- execution journals resume without repeating completed writes');
console.log('- five consecutive real Workspace repair runs remain mandatory');
