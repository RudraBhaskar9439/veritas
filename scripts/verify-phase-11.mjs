import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'docs/architecture-decisions/0011-reproducible-evaluation-corpus.md',
  'docs/verification/phase-11.md',
  'evaluation/README.md',
  'evaluation/results.json',
  'evaluation/scenarios.json',
  'evaluation/thresholds.json',
  'scripts/run_evaluation.py'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 11 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const scenarios = JSON.parse(readFileSync(resolve(root, 'evaluation/scenarios.json'), 'utf8'));
if (scenarios.length !== 40 || new Set(scenarios.map((item) => item.id)).size !== 40) {
  console.error('Phase 11 verification failed: expected exactly forty unique scenarios');
  process.exit(1);
}
if (scenarios.some((item) => Object.hasOwn(item, 'actual'))) {
  console.error('Phase 11 verification failed: scenarios must not contain pre-filled actual outputs');
  process.exit(1);
}
const categoryCounts = scenarios.reduce((counts, item) => {
  counts[item.category] = (counts[item.category] ?? 0) + 1;
  return counts;
}, {});
for (const category of [
  'semantic_delta',
  'lineage',
  'repair_policy',
  'three_way_merge',
  'certification'
]) {
  if (categoryCounts[category] !== 8) {
    console.error(`Phase 11 verification failed: ${category} must contain eight scenarios`);
    process.exit(1);
  }
}

const checks = [
  ...(process.argv.includes('--ci')
    ? []
    : [['Cumulative Phase 10 gate', 'node', ['scripts/verify-phase-10.mjs']]]),
  ['Evaluation harness lint', 'uv', ['run', 'ruff', 'check', 'scripts/run_evaluation.py']],
  ['Published forty-scenario benchmark', 'uv', ['run', 'python', 'scripts/run_evaluation.py', '--check']],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-11] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 11 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 11 deterministic evaluation verification passed.');
console.log('- forty scenarios execute production decision functions');
console.log('- all five strata pass 8/8 with zero false certificates');
console.log('- the dataset, thresholds, and published metrics are reproducible');
console.log('- live Workspace samples exist; p50/p95, model usage, and exact Cloud cost remain partial');
