export type ViewId = 'overview' | 'lineage' | 'verification';

export interface ClaimChange {
  id: string;
  shortLabel: string;
  before: string;
  after: string;
  transformation: string;
  evidence: string;
  policy: string;
  risk: 'reversible' | 'decision';
  riskLabel: string;
  targetCount: number;
}

export const incident = {
  claims: [
    {
      id: 'churn-value',
      shortLabel: 'Churn value',
      before: 'Q3 customer churn is 4%.',
      after: 'Q3 customer churn is 9%.',
      transformation: 'identity_percent@1',
      evidence: 'Metrics!B17 · sheet-v2',
      policy: 'Auto-execute',
      risk: 'reversible',
      riskLabel: 'Reversible fact',
      targetCount: 2,
    },
    {
      id: 'churn-direction',
      shortLabel: 'Churn direction',
      before: 'Customer churn improved during Q3.',
      after: 'Customer churn worsened during Q3.',
      transformation: 'compare_to_previous_quarter@1',
      evidence: 'Metrics!B17 ↔ Metrics!B16',
      policy: 'Auto + correction draft',
      risk: 'reversible',
      riskLabel: 'Reversible fact',
      targetCount: 2,
    },
    {
      id: 'retention-target',
      shortLabel: 'Retention target',
      before: 'The retention target has been achieved.',
      after: 'The retention target has not been achieved.',
      transformation: 'churn_lte_target_5_percent@1',
      evidence: 'Metrics!B17 ≤ 5% · false',
      policy: 'Human approval required',
      risk: 'decision',
      riskLabel: 'Decision-changing',
      targetCount: 2,
    },
    {
      id: 'acquisition',
      shortLabel: 'Acquisition spend',
      before: 'The company should increase acquisition spend.',
      after: 'The company should pause the planned increase in acquisition spend.',
      transformation: 'recommend_if_churn_lte_5_percent@1',
      evidence: 'Metrics!B17 ≤ 5% · false',
      policy: 'Human approval required',
      risk: 'decision',
      riskLabel: 'Decision-changing',
      targetCount: 3,
    },
  ] satisfies ReadonlyArray<ClaimChange>,
  artifacts: [
    {
      id: 'board-memo',
      code: 'D',
      surface: 'Google Docs',
      name: 'Board memo',
      targetCount: 2,
      action: 'Replace 2 named-range spans',
      guardrail: 'requiredRevisionId',
      result: 'repaired',
    },
    {
      id: 'exec-deck',
      code: 'S',
      surface: 'Google Slides',
      name: 'Executive deck',
      targetCount: 3,
      action: 'Replace 3 registered shapes',
      guardrail: 'requiredRevisionId',
      result: 'repaired',
    },
    {
      id: 'investor-email',
      code: 'G',
      surface: 'Gmail',
      name: 'Investor update',
      targetCount: 2,
      action: 'Create unsent corrections',
      guardrail: 'immutable original',
      result: 'drafted',
    },
    {
      id: 'retention-plan',
      code: 'D',
      surface: 'Google Docs',
      name: 'Retention plan',
      targetCount: 1,
      action: 'Replace 1 named-range span',
      guardrail: 'human approved',
      result: 'repaired',
    },
    {
      id: 'acquisition-task',
      code: 'T',
      surface: 'Google Tasks',
      name: 'Acquisition task',
      targetCount: 1,
      action: 'Patch registered note text',
      guardrail: 'If-Match ETag',
      result: 'updated',
    },
  ],
  timeline: [
    { time: '10:42:07', label: 'Detected', detail: 'Sheet delta accepted' },
    { time: '10:42:08', label: 'Traced', detail: '9 lineage paths' },
    { time: '10:42:10', label: 'Approved', detail: '2 human decisions' },
    { time: '10:42:13', label: 'Repaired', detail: '9 terminal steps' },
    { time: '10:42:15', label: 'Verified', detail: '36 checks passed' },
    { time: '10:42:16', label: 'Certified', detail: 'Scoped record issued' },
  ],
  coverage: { claims: 8, targets: 13, protectedArtifacts: 5, sources: 6 },
  certificate: {
    shortId: 'CERT-7A92',
    statement:
      'All monitored claims in this Decision Packet are consistent with their registered evidence versions as of the stated timestamp.',
  },
  checks: [
    { label: 'Repair run terminal', detail: '9 of 9 planned steps succeeded', receipt: 'run·e1c4' },
    {
      label: 'Source set fresh',
      detail: '6 causal snapshots are still current',
      receipt: 'src·d09f',
    },
    {
      label: 'Claims recomputed',
      detail: '8 deterministic recipes reproduced',
      receipt: 'clm·a881',
    },
    { label: 'Targets re-read', detail: '13 Workspace targets match', receipt: 'tgt·29b3' },
    {
      label: 'Human work preserved',
      detail: '5 protected projections unchanged',
      receipt: 'hsh·c443',
    },
    {
      label: 'Correction drafts present',
      detail: '2 corrections independently read',
      receipt: 'drf·8d2a',
    },
    { label: 'Coverage complete', detail: '0 candidate edges entered scope', receipt: 'cov·1000' },
  ],
  evidence: [
    {
      id: 'churn',
      label: 'Customer churn',
      kind: 'Google Sheets',
      anchor: 'Metrics!B17',
      version: 'sheet-v2',
      snapshot: 'snap·3a91',
    },
    {
      id: 'previous-churn',
      label: 'Previous churn',
      kind: 'Google Sheets',
      anchor: 'Metrics!B16',
      version: 'sheet-v1',
      snapshot: 'snap·c882',
    },
    {
      id: 'revenue',
      label: 'Q3 revenue',
      kind: 'Google Sheets',
      anchor: 'Metrics!B5',
      version: 'sheet-v1',
      snapshot: 'snap·f230',
    },
    {
      id: 'pipeline',
      label: 'Qualified pipeline',
      kind: 'Google Sheets',
      anchor: 'Metrics!B8',
      version: 'sheet-v1',
      snapshot: 'snap·b122',
    },
    {
      id: 'nps',
      label: 'Net Promoter Score',
      kind: 'Google Sheets',
      anchor: 'Metrics!B20',
      version: 'sheet-v1',
      snapshot: 'snap·4cc9',
    },
    {
      id: 'launch',
      label: 'Launch date',
      kind: 'Google Docs',
      anchor: 'launch-date',
      version: 'doc-v1',
      snapshot: 'snap·71dd',
    },
  ],
} as const;
