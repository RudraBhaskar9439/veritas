import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const requiredFiles = [
  'README.md',
  'docs/product-contract.md',
  'docs/demo-scenario.md',
  'docs/phases.md',
  'docs/verification-strategy.md',
  'docs/architecture-decisions/0001-claim-manifest.md',
  'docs/verification/phase-0.md',
  'schemas/claim-manifest.schema.json',
  'fixtures/demo/q3-executive-review.json',
  'fixtures/demo/expected-churn-impact.json'
];

const failures = [];
for (const file of requiredFiles) {
  if (!existsSync(resolve(root, file))) failures.push(`missing required file: ${file}`);
}

const readJson = (file) => JSON.parse(readFileSync(resolve(root, file), 'utf8'));
const schema = readJson('schemas/claim-manifest.schema.json');
const manifest = readJson('fixtures/demo/q3-executive-review.json');
const impact = readJson('fixtures/demo/expected-churn-impact.json');

const unique = (values) => new Set(values).size === values.length;
const sourceIds = new Set(manifest.sources.map((source) => source.sourceId));
const artifactIds = new Set(manifest.artifacts.map((artifact) => artifact.artifactId));
const claimIds = new Set(manifest.claims.map((claim) => claim.claimId));

if (schema.$schema !== 'https://json-schema.org/draft/2020-12/schema') failures.push('schema must use JSON Schema draft 2020-12');
if (manifest.claims.length !== 8) failures.push(`expected 8 canonical claims, found ${manifest.claims.length}`);
if (manifest.artifacts.length !== 5) failures.push(`expected 5 canonical artifacts, found ${manifest.artifacts.length}`);
if (!unique([...sourceIds])) failures.push('source IDs must be unique');
if (!unique([...artifactIds])) failures.push('artifact IDs must be unique');
if (!unique([...claimIds])) failures.push('claim IDs must be unique');

for (const claim of manifest.claims) {
  if (claim.provenance !== 'registered') failures.push(`canonical claim ${claim.claimId} is not registered`);
  if (!claim.sourceIds.length) failures.push(`claim ${claim.claimId} has no source`);
  if (!claim.artifactAnchors.length) failures.push(`claim ${claim.claimId} has no artifact anchor`);
  if (!claim.transformation?.name || !claim.transformation?.version) {
    failures.push(`claim ${claim.claimId} lacks a versioned transformation`);
  }
  for (const sourceId of claim.sourceIds) {
    if (!sourceIds.has(sourceId)) failures.push(`claim ${claim.claimId} references unknown source ${sourceId}`);
  }
  for (const anchor of claim.artifactAnchors) {
    if (!artifactIds.has(anchor.artifactId)) failures.push(`claim ${claim.claimId} references unknown artifact ${anchor.artifactId}`);
  }
}

for (const artifact of manifest.artifacts) {
  if (!artifact.baseRevisionId) failures.push(`artifact ${artifact.artifactId} lacks a base revision`);
}

if (impact.affectedClaimIds.length !== 4) failures.push('churn change must affect exactly 4 claims');
if (impact.unaffectedClaimIds.length !== 4) failures.push('churn change must leave exactly 4 claims unaffected');
if (impact.affectedArtifactIds.length !== 5) failures.push('churn change must affect exactly 5 artifacts');
for (const claimId of [...impact.affectedClaimIds, ...impact.unaffectedClaimIds]) {
  if (!claimIds.has(claimId)) failures.push(`impact fixture references unknown claim ${claimId}`);
}
for (const artifactId of impact.affectedArtifactIds) {
  if (!artifactIds.has(artifactId)) failures.push(`impact fixture references unknown artifact ${artifactId}`);
}

const claimsDependingOnChangedSource = manifest.claims
  .filter((claim) => claim.sourceIds.includes(impact.changedSourceId))
  .map((claim) => claim.claimId)
  .sort();
const expectedAffected = [...impact.affectedClaimIds].sort();
if (JSON.stringify(claimsDependingOnChangedSource) !== JSON.stringify(expectedAffected)) {
  failures.push('expected impact does not equal registered lineage from src-churn');
}

const derivedArtifacts = [...new Set(manifest.claims
  .filter((claim) => impact.affectedClaimIds.includes(claim.claimId))
  .flatMap((claim) => claim.artifactAnchors.map((anchor) => anchor.artifactId)))].sort();
const expectedArtifacts = [...impact.affectedArtifactIds].sort();
if (JSON.stringify(derivedArtifacts) !== JSON.stringify(expectedArtifacts)) {
  failures.push('expected artifact blast radius does not match registered claim anchors');
}

const immutableAffected = manifest.artifacts
  .filter((artifact) => impact.affectedArtifactIds.includes(artifact.artifactId) && artifact.mutability === 'immutable')
  .map((artifact) => artifact.artifactId)
  .sort();
const expectedDraftOnly = [...impact.draftOnlyArtifactIds].sort();
if (JSON.stringify(immutableAffected) !== JSON.stringify(expectedDraftOnly)) {
  failures.push('draft-only artifact expectation must match affected immutable artifacts');
}

if (failures.length) {
  console.error('Phase 0 verification failed:');
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exit(1);
}

console.log('Phase 0 verification passed.');
console.log(`- ${manifest.claims.length} registered claims`);
console.log(`- ${manifest.artifacts.length} downstream artifacts`);
console.log(`- ${impact.affectedClaimIds.length} affected and ${impact.unaffectedClaimIds.length} unaffected claims for the canonical churn change`);
console.log(`- ${impact.affectedArtifactIds.length} artifacts in the registered blast radius`);
console.log('- immutable communication correctly resolves to draft-only correction policy');
