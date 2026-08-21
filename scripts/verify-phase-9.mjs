import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'apps/web/public/og.png',
  'apps/web/src/App.test.tsx',
  'apps/web/src/App.tsx',
  'apps/web/src/incident.ts',
  'apps/web/src/styles.css',
  'docs/architecture-decisions/0009-evidence-room-command-center.md',
  'docs/verification/phase-9.md'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 9 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const app = readFileSync(resolve(root, 'apps/web/src/App.tsx'), 'utf8');
const fixture = readFileSync(resolve(root, 'apps/web/src/incident.ts'), 'utf8');
const styles = readFileSync(resolve(root, 'apps/web/src/styles.css'), 'utf8');
for (const contract of [
  'Replay incident',
  'Blast radius',
  'The repair agent does not grade its own work.',
  'Candidate lineage and unregistered prose',
  'localStorage'
]) {
  if (!app.includes(contract)) {
    console.error(`Phase 9 verification failed: Command Center lacks ${contract}`);
    process.exit(1);
  }
}
for (const contract of [
  'All monitored claims in this Decision Packet',
  'Metrics!B17',
  'candidate edges entered scope'
]) {
  if (!fixture.includes(contract)) {
    console.error(`Phase 9 verification failed: incident fixture lacks ${contract}`);
    process.exit(1);
  }
}
for (const contract of ['prefers-reduced-motion', ':focus-visible', '@media print']) {
  if (!styles.includes(contract)) {
    console.error(`Phase 9 verification failed: styles lack ${contract}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 8 gate', 'node', ['scripts/verify-phase-8.mjs']]]),
  ['Web lint', 'pnpm', ['lint']],
  ['Web types', 'pnpm', ['typecheck']],
  ['Web interaction tests', 'pnpm', ['test']],
  ['Web production build', 'pnpm', ['build']],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-9] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 9 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 9 pre-browser Command Center verification passed.');
console.log('- the opening view proves the full evidence-to-certificate story');
console.log('- diffs, lineage, receipts, protected regions, and scope are inspectable');
console.log('- navigation and claim selection survive refresh');
console.log('- hosted browser E2E and accessibility audit remain mandatory');
