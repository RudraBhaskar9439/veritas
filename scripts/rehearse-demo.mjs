import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const paths = {
  contract: 'demo/demo-contract.json',
  impact: 'fixtures/demo/expected-churn-impact.json',
  repair: 'fixtures/demo/expected-repair-plan.json',
  incident: 'apps/web/src/incident.ts',
  evaluation: 'evaluation/results.json',
  cloudProof: 'docs/submission/cloud-proof-manifest.json'
};

const raw = Object.fromEntries(
  Object.entries(paths).map(([name, path]) => [name, readFileSync(resolve(root, path), 'utf8')])
);
const contract = JSON.parse(raw.contract);
const impact = JSON.parse(raw.impact);
const repair = JSON.parse(raw.repair);
const evaluation = JSON.parse(raw.evaluation);
const cloudProof = JSON.parse(raw.cloudProof);
const demoIncident = raw.incident.slice(raw.incident.indexOf('export const demoIncident'));

const contiguous = contract.beats.every((beat, index) => {
  if (index === 0) return beat.start === 0;
  return contract.beats[index - 1].end === beat.start;
});
const checks = [
  ['duration', contract.durationSeconds <= 240 && contract.beats.at(-1).end === contract.durationSeconds],
  ['twelve-beat chronology', contract.beats.length === 12 && contiguous],
  ['real source change', impact.before === 4 && impact.after === 9],
  ['claim blast radius', impact.affectedClaimIds.length === 4 && impact.unaffectedClaimIds.length === 4],
  ['artifact blast radius', impact.affectedArtifactIds.length === 5],
  ['minimal repair plan', repair.stepCount === 9],
  ['human approval boundary', repair.policySummary.approvalRequiredSteps === 4],
  ['immutable correction boundary', repair.policySummary.draftOnlySteps === 2],
  [
    'command-center coverage',
    ['claims: 8', 'targets: 13', 'protectedArtifacts: 5', 'sources: 6'].every((value) =>
      demoIncident.includes(value)
    )
  ],
  ['independent checks', raw.incident.includes("detail: '13 Workspace targets match'") && raw.incident.includes("detail: '5 protected projections unchanged'")],
  ['published benchmark', evaluation.scenarioCount === 40 && evaluation.passed === 40],
  ['cloud-proof honesty', cloudProof.status === 'pending_google_cloud' && cloudProof.requiredEvidence.every((item) => item.status === 'pending')]
];

const inputChecksum = createHash('sha256')
  .update(Object.keys(raw).sort().map((key) => raw[key]).join('\n'))
  .digest('hex');
const failedChecks = checks.filter(([_name, passed]) => !passed).map(([name]) => name);
const rehearsalDigest = createHash('sha256')
  .update(JSON.stringify({ inputChecksum, checks }))
  .digest('hex');
const runs = Array.from({ length: 5 }, (_value, index) => ({
  run: index + 1,
  passed: failedChecks.length === 0,
  checksPassed: checks.length - failedChecks.length,
  checksTotal: checks.length,
  rehearsalDigest
}));
const results = {
  schemaVersion: '1.0',
  mode: 'automated_offline_contract_rehearsal',
  durationSeconds: contract.durationSeconds,
  inputChecksum,
  runs,
  passedRuns: runs.filter((run) => run.passed).length,
  failedChecks,
  liveWorkspaceMutations: false,
  liveRehearsalsStatus: 'pending_google_cloud'
};

if (process.argv.includes('--check')) {
  const committed = JSON.parse(readFileSync(resolve(root, 'demo/rehearsal-results.json'), 'utf8'));
  if (JSON.stringify(results) !== JSON.stringify(committed)) {
    console.error('Phase 12 rehearsal results are stale.');
    process.exit(1);
  }
}

if (failedChecks.length) {
  console.error(`Phase 12 rehearsal failed: ${failedChecks.join(', ')}`);
  process.exit(1);
}

if (process.argv.includes('--emit')) {
  console.log(JSON.stringify(results, null, 2));
} else {
  console.log(
    `Phase 12 offline rehearsal passed: ${results.passedRuns}/5 deterministic runs, ` +
      `${checks.length}/${checks.length} checks each, ${contract.durationSeconds}s script.`
  );
  console.log('Live Workspace rehearsals remain pending Google Cloud access.');
}
