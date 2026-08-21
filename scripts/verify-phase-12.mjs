import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'demo/demo-contract.json',
  'demo/rehearsal-results.json',
  'docs/architecture.md',
  'docs/architecture-decisions/0012-proof-bound-submission.md',
  'docs/runbooks/cloud-deployment.md',
  'docs/submission/checklist.md',
  'docs/submission/claim-evidence-matrix.md',
  'docs/submission/cloud-proof-manifest.json',
  'docs/submission/demo-script.md',
  'docs/submission/devpost-draft.md',
  'docs/submission/recording-runbook.md',
  'docs/verification/phase-12.md',
  'scripts/rehearse-demo.mjs'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 12 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const contract = JSON.parse(readFileSync(resolve(root, 'demo/demo-contract.json'), 'utf8'));
if (contract.durationSeconds > 240 || contract.beats.length !== 12) {
  console.error('Phase 12 verification failed: demo must contain twelve beats within four minutes');
  process.exit(1);
}
const proof = JSON.parse(
  readFileSync(resolve(root, 'docs/submission/cloud-proof-manifest.json'), 'utf8')
);
if (
  proof.status !== 'pending_google_cloud' ||
  proof.requiredEvidence.length !== 12 ||
  proof.requiredEvidence.some((item) => item.status !== 'pending')
) {
  console.error('Phase 12 verification failed: unproven Cloud evidence was marked complete');
  process.exit(1);
}
const devpost = readFileSync(resolve(root, 'docs/submission/devpost-draft.md'), 'utf8');
for (const forbidden of ['Veritas guarantees correctness', 'This document is completely true']) {
  if (devpost.includes(forbidden)) {
    console.error(`Phase 12 verification failed: Devpost draft contains ${forbidden}`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 11 gate', 'node', ['scripts/verify-phase-11.mjs']]]),
  ['Five deterministic offline rehearsals', 'node', ['scripts/rehearse-demo.mjs', '--check']],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-12] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 12 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 12 credit-independent submission verification passed.');
console.log('- the four-minute narrative, proof matrix, diagrams, and runbooks are complete');
console.log('- five deterministic offline rehearsals pass 12/12 checks each');
console.log('- every unproven live Cloud item remains explicitly pending');
console.log('- the real video and five live rehearsals require Google Cloud access');

