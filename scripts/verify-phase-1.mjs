import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  '.github/workflows/ci.yml',
  'apps/web/Dockerfile',
  'apps/web/src/App.tsx',
  'compose.yaml',
  'docs/verification/phase-1.md',
  'infra/terraform/main.tf',
  'infra/terraform/versions.tf',
  'services/runtime/Dockerfile',
  'services/runtime/src/veritas_runtime/api.py',
  'services/runtime/src/veritas_runtime/ingress.py',
  'services/runtime/src/veritas_runtime/worker.py',
  'services/runtime/tests/test_health.py',
  'uv.lock',
  'pnpm-lock.yaml'
];

const missing = requiredFiles.filter((file) => !existsSync(resolve(root, file)));
if (missing.length) {
  console.error('Phase 1 verification failed:');
  missing.forEach((file) => console.error(`- missing required file: ${file}`));
  process.exit(1);
}

const checks = [
  ['Phase 0 contract', 'node', ['scripts/verify-phase-0.mjs']],
  ['Python lint', 'uv', ['run', 'ruff', 'check', '.']],
  ['Python format', 'uv', ['run', 'ruff', 'format', '--check', '.']],
  ['Python types', 'uv', ['run', 'mypy']],
  ['Python tests', 'uv', ['run', 'pytest']],
  ['Web lint', 'pnpm', ['lint']],
  ['Web types', 'pnpm', ['typecheck']],
  ['Web tests', 'pnpm', ['test']],
  ['Web build', 'pnpm', ['build']],
  ['Compose contract', 'docker', ['compose', 'config', '--quiet']],
  ['Git whitespace', 'git', ['diff', '--check']]
];

for (const [label, command, args] of checks) {
  console.log(`\n[phase-1] ${label}`);
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    console.error(`Phase 1 verification failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

console.log('\nPhase 1 local verification passed.');
console.log('- three fail-closed runtime roles expose correlated health contracts');
console.log('- web command center passes lint, types, tests, and production build');
console.log('- container and Google Cloud infrastructure contracts are present');
console.log('- CI remains the authoritative Terraform and container-build gate');
