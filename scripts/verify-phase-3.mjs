import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0003-packet-materialization-and-manifest-commit.md',
  'docs/verification/phase-3.md',
  'fixtures/demo/q3-generation-request.json',
  'schemas/claim-manifest.schema.json',
  'services/runtime/migrations/0002_claim_manifests.sql',
  'services/runtime/src/veritas_runtime/packets/database.py',
  'services/runtime/src/veritas_runtime/packets/generator.py',
  'services/runtime/src/veritas_runtime/packets/models.py',
  'services/runtime/src/veritas_runtime/packets/routes.py',
  'services/runtime/src/veritas_runtime/packets/transformations.py',
  'services/runtime/tests/test_packet_database.py',
  'services/runtime/tests/test_packet_generator.py',
  'services/runtime/tests/test_packet_routes.py',
  'services/runtime/tests/test_packet_transformations.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 3 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const migration = readFileSync(
  resolve(root, 'services/runtime/migrations/0002_claim_manifests.sql'),
  'utf8'
).toLowerCase();
for (const forbiddenColumn of ['source_value', 'source_context', 'access_token', 'refresh_token']) {
  if (migration.includes(forbiddenColumn)) {
    console.error(`Phase 3 verification failed: forbidden manifest column ${forbiddenColumn}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 2 gate', 'node', ['scripts/verify-phase-2.mjs']]]),
  [
    'Phase 3 packet and provenance tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_packet_database.py',
      'services/runtime/tests/test_packet_generator.py',
      'services/runtime/tests/test_packet_routes.py',
      'services/runtime/tests/test_packet_transformations.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-3] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 3 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 3 pre-live implementation verification passed.');
console.log('- canonical claims are calculated from validated source snapshots');
console.log('- provenance anchors come from materialized artifact responses');
console.log('- versioned manifests are idempotent, checksummed, and fail closed');
console.log('- the real Google Workspace packet-generation gate remains mandatory');
