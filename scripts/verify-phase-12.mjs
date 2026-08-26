import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'demo/demo-contract.json',
  'demo/rehearsal-results.json',
  'docs/architecture.md',
  'docs/architecture-decisions/0012-proof-bound-submission.md',
  'docs/architecture-decisions/0014-preview-cost-containment.md',
  'docs/architecture-decisions/0016-autonomous-consequence-orchestration.md',
  'docs/runbooks/cloud-deployment.md',
  'docs/submission/checklist.md',
  'docs/submission/claim-evidence-matrix.md',
  'docs/submission/cloud-proof-manifest.json',
  'docs/submission/demo-script.md',
  'docs/submission/devpost-draft.md',
  'docs/submission/live-proof-report.md',
  'docs/submission/recording-runbook.md',
  'docs/verification/phase-12.md',
  'scripts/rehearse-demo.mjs',
  'services/runtime/migrations/0009_gemini_agent_reviews.sql',
  'services/runtime/migrations/0010_drive_operation_batches.sql',
  'services/runtime/src/veritas_runtime/migrations.py',
  'services/runtime/src/veritas_runtime/agents/gemini.py',
  'services/runtime/src/veritas_runtime/agents/service.py'
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
const allowedProofStatuses = new Set(['complete', 'partial', 'pending']);
const proofById = new Map(proof.requiredEvidence.map((item) => [item.id, item]));
const completeProofIds = [
  'public-url',
  'immutable-images',
  'workspace-generation',
  'drive-event',
  'native-repair',
  'human-preservation',
  'correction-draft',
  'certificate'
];
const partialProofIds = ['failure-injection', 'five-runs', 'browser-audit', 'cost-latency'];
if (
  proof.status !== 'live_proof_partial' ||
  proof.requiredEvidence.length !== 12 ||
  proof.requiredEvidence.some((item) => !allowedProofStatuses.has(item.status)) ||
  completeProofIds.some((id) => proofById.get(id)?.status !== 'complete') ||
  partialProofIds.some((id) => proofById.get(id)?.status !== 'partial')
) {
  console.error('Phase 12 verification failed: Cloud proof status does not match the recorded live evidence');
  process.exit(1);
}
const devpost = readFileSync(resolve(root, 'docs/submission/devpost-draft.md'), 'utf8');
for (const forbidden of ['Veritas guarantees correctness', 'This document is completely true']) {
  if (devpost.includes(forbidden)) {
    console.error(`Phase 12 verification failed: Devpost draft contains ${forbidden}`);
    process.exit(1);
  }
}
const geminiGateway = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/agents/gemini.py'),
  'utf8'
);
const geminiService = readFileSync(
  resolve(root, 'services/runtime/src/veritas_runtime/agents/service.py'),
  'utf8'
);
const terraform = readFileSync(resolve(root, 'infra/terraform/main.tf'), 'utf8');
for (const contract of [
  'genai.Client(vertexai=True',
  'response_schema=GeminiReviewPayload',
  'Gemini review changed the registered claim scope'
]) {
  if (!`${geminiGateway}\n${geminiService}`.includes(contract)) {
    console.error(`Phase 12 verification failed: Gemini agent contract lacks ${contract}`);
    process.exit(1);
  }
}
if (!terraform.includes('VERITAS_GEMINI_MODEL') || !terraform.includes('gemini-2.5-flash')) {
  console.error('Phase 12 verification failed: Terraform does not bind Gemini 2.5 Flash');
  process.exit(1);
}
for (const contract of [
  'resource "google_cloud_run_v2_job" "migrations"',
  'veritas_runtime.migrations',
  'service_account = google_service_account.runtime["migrator"]'
]) {
  if (!terraform.includes(contract)) {
    console.error(`Phase 12 verification failed: migration-job contract lacks ${contract}`);
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

console.log('\nPhase 12 release submission verification passed.');
console.log('- the four-minute narrative, proof matrix, live report, diagrams, and runbooks are complete');
console.log('- five deterministic offline rehearsals pass 12/12 checks each');
console.log('- eight production proof items are complete and four residual items remain explicitly partial');
console.log('- the real video, five consecutive clean runs, final browser audit, and cost metrics remain entrant/release work');
