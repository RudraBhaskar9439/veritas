import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0004-drive-notifications-cursors-and-snapshots.md',
  'docs/verification/phase-4.md',
  'services/runtime/migrations/0003_drive_change_capture.sql',
  'services/runtime/src/veritas_runtime/changes/database.py',
  'services/runtime/src/veritas_runtime/changes/drive.py',
  'services/runtime/src/veritas_runtime/changes/extractor.py',
  'services/runtime/src/veritas_runtime/changes/processor.py',
  'services/runtime/src/veritas_runtime/changes/registration.py',
  'services/runtime/src/veritas_runtime/changes/routes.py',
  'services/runtime/src/veritas_runtime/changes/semantic.py',
  'services/runtime/src/veritas_runtime/changes/service.py',
  'services/runtime/src/veritas_runtime/changes/snapshots.py',
  'services/runtime/src/veritas_runtime/changes/tokens.py',
  'services/runtime/tests/test_change_database.py',
  'services/runtime/tests/test_change_processor.py',
  'services/runtime/tests/test_drive_changes_client.py',
  'services/runtime/tests/test_evidence_extractor.py',
  'services/runtime/tests/test_gcs_snapshot_store.py',
  'services/runtime/tests/test_semantic_snapshots.py',
  'services/runtime/tests/test_watch_lifecycle.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 4 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const migration = readFileSync(
  resolve(root, 'services/runtime/migrations/0003_drive_change_capture.sql'),
  'utf8'
).toLowerCase();
for (const contract of [
  'primary key (channel_id, message_number)',
  'unique (subject, packet_id, source_id, workspace_version)',
  'unique (subject, packet_id, source_id, content_hash)'
]) {
  if (!migration.includes(contract)) {
    console.error(`Phase 4 verification failed: migration lacks ${contract}`);
    process.exit(1);
  }
}

const driveClient = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/changes/drive.py'),
  'utf8'
);
if (driveClient.includes('changeId')) {
  console.error('Phase 4 verification failed: Drive v3 client uses legacy changeId');
  process.exit(1);
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 3 gate', 'node', ['scripts/verify-phase-3.mjs']]]),
  [
    'Phase 4 change-capture tests',
    'uv',
    [
      'run',
      'pytest',
      '--no-cov',
      '-q',
      'services/runtime/tests/test_change_database.py',
      'services/runtime/tests/test_change_factory.py',
      'services/runtime/tests/test_change_processor.py',
      'services/runtime/tests/test_change_routes.py',
      'services/runtime/tests/test_change_tokens.py',
      'services/runtime/tests/test_drive_changes_client.py',
      'services/runtime/tests/test_evidence_extractor.py',
      'services/runtime/tests/test_evidence_registration.py',
      'services/runtime/tests/test_gcs_snapshot_store.py',
      'services/runtime/tests/test_semantic_snapshots.py',
      'services/runtime/tests/test_watch_lifecycle.py'
    ]
  ],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-4] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 4 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 4 pre-live implementation verification passed.');
console.log('- authenticated Drive notifications are deduplicated into a durable outbox');
console.log('- overlapping watch renewal and the early-sync race are verified');
console.log('- registered native evidence becomes immutable content-addressed snapshots');
console.log('- duplicate, cosmetic, and meaningful deltas are deterministically separated');
console.log('- the real Drive notification and Cloud Storage gate remains mandatory');
