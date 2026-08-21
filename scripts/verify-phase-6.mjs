import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0006-deterministic-repair-plans-and-human-approvals.md',
  'docs/verification/phase-6.md',
  'fixtures/demo/expected-repair-plan.json',
  'services/runtime/migrations/0005_repair_plans.sql',
  'services/runtime/src/veritas_runtime/repairs/database.py',
  'services/runtime/src/veritas_runtime/repairs/models.py',
  'services/runtime/src/veritas_runtime/repairs/planner.py',
  'services/runtime/src/veritas_runtime/repairs/policy.py',
  'services/runtime/src/veritas_runtime/repairs/routes.py',
  'services/runtime/src/veritas_runtime/repairs/service.py',
  'services/runtime/tests/test_repair_database.py',
  'services/runtime/tests/test_repair_planner_service.py',
  'services/runtime/tests/test_repair_policy.py',
  'services/runtime/tests/test_repair_routes.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 6 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const expected = JSON.parse(
  readFileSync(resolve(root, 'fixtures/demo/expected-repair-plan.json'), 'utf8')
);
if (
  expected.stepCount !== 9 ||
  expected.policySummary.autoExecuteSteps !== 3 ||
  expected.policySummary.approvalRequiredSteps !== 4 ||
  expected.policySummary.draftOnlySteps !== 2 ||
  expected.policySummary.blockedSteps !== 0
) {
  console.error('Phase 6 verification failed: canonical repair policy fixture changed');
  process.exit(1);
}

const policyBoundary = [
  'services/runtime/src/veritas_runtime/repairs/planner.py',
  'services/runtime/src/veritas_runtime/repairs/policy.py'
].map((file) => readFileSync(resolve(root, file), 'utf8').toLowerCase()).join('\n');
for (const forbidden of ['vertexai', 'gemini', 'embedding', 'similarity']) {
  if (policyBoundary.includes(forbidden)) {
    console.error(`Phase 6 verification failed: deterministic boundary contains ${forbidden}`);
    process.exit(1);
  }
}

const migration = readFileSync(
  resolve(root, 'services/runtime/migrations/0005_repair_plans.sql'),
  'utf8'
).toLowerCase();
for (const contract of [
  'idempotency_key varchar(1024) not null unique',
  'create table repair_approvals',
  'create table repair_approval_events'
]) {
  if (!migration.includes(contract)) {
    console.error(`Phase 6 verification failed: migration lacks ${contract}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 5 gate', 'node', ['scripts/verify-phase-5.mjs']]]),
  [
    'Phase 6 repair-policy tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_repair_database.py',
      'services/runtime/tests/test_repair_planner_service.py',
      'services/runtime/tests/test_repair_policy.py',
      'services/runtime/tests/test_repair_routes.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-6] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 6 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 6 typed-repair verification passed.');
console.log('- canonical incident produces 9 minimal typed repair steps');
console.log('- policy yields 3 automatic, 4 approval-gated, and 2 draft-only steps');
console.log('- immutable email is correction-draft-only and agent self-approval is forbidden');
console.log('- plans and human decisions are checksummed, audited, and idempotent');
