import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0005-registered-lineage-blast-radius.md',
  'docs/verification/phase-5.md',
  'fixtures/demo/expected-churn-impact.json',
  'services/runtime/migrations/0004_impact_reports.sql',
  'services/runtime/src/veritas_runtime/lineage/database.py',
  'services/runtime/src/veritas_runtime/lineage/engine.py',
  'services/runtime/src/veritas_runtime/lineage/models.py',
  'services/runtime/src/veritas_runtime/lineage/routes.py',
  'services/runtime/src/veritas_runtime/lineage/service.py',
  'services/runtime/tests/test_lineage_database.py',
  'services/runtime/tests/test_lineage_engine.py',
  'services/runtime/tests/test_lineage_service_routes.py',
  'services/runtime/tests/test_manifest_graph_contract.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 5 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const engine = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/lineage/engine.py'),
  'utf8'
);
for (const forbidden of ['vertexai', 'gemini', 'embedding', 'similarity']) {
  if (engine.toLowerCase().includes(forbidden)) {
    console.error(`Phase 5 verification failed: lineage engine contains ${forbidden}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 4 gate', 'node', ['scripts/verify-phase-4.mjs']]]),
  [
    'Phase 5 registered-lineage tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_lineage_database.py',
      'services/runtime/tests/test_lineage_engine.py',
      'services/runtime/tests/test_lineage_service_routes.py',
      'services/runtime/tests/test_manifest_graph_contract.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-5] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 5 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 5 registered-lineage verification passed.');
console.log('- canonical churn change resolves to exactly 4 claims and 5 artifacts');
console.log('- 9 exact source-to-claim-to-anchor paths explain the blast radius');
console.log('- candidate and wording-similar unregistered edges are excluded');
console.log('- reports are subject-scoped, versioned, checksummed, and idempotent');
