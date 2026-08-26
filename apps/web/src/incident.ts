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

export interface ArtifactChange {
  id: string;
  code: string;
  surface: string;
  name: string;
  targetCount: number;
  action: string;
  guardrail: string;
  result: string;
}

export interface IncidentApproval {
  approvalId: string;
  planId: string;
  runId: string | null;
  claimId: string;
  claimLabel: string;
  status: 'pending' | 'approved' | 'rejected';
  reason: string | null;
}

export interface Incident {
  id: string;
  packetId: string;
  runId: string | null;
  status: 'awaiting_approval' | 'repairing' | 'verified' | 'attention';
  source: 'live' | 'demo';
  headline: string;
  summary: string;
  detectedAt: string;
  updatedAt: string;
  claims: ReadonlyArray<ClaimChange>;
  artifacts: ReadonlyArray<ArtifactChange>;
  timeline: ReadonlyArray<{
    time: string;
    occurredAt: string;
    label: string;
    detail: string;
    receipt: string;
  }>;
  coverage: {
    claims: number;
    affectedClaims: number;
    targets: number;
    verifiedTargets: number;
    protectedArtifacts: number;
    verifiedProtectedArtifacts: number;
    sources: number;
    lineagePaths: number;
  };
  certificate: { shortId: string; statement: string; issuedAt: string } | null;
  checks: ReadonlyArray<{ label: string; detail: string; receipt: string; passed: boolean }>;
  evidence: ReadonlyArray<{
    id: string;
    label: string;
    kind: string;
    anchor: string;
    version: string;
    snapshot: string;
    snapshotId: string;
    contentHash: string;
    capturedAt: string;
    changed: boolean;
    current: boolean;
  }>;
  approvals: ReadonlyArray<IncidentApproval>;
  agentReview: {
    model: string;
    disposition: 'proceed' | 'escalate';
    rationale: string;
    riskFlags: ReadonlyArray<string>;
    receipt: string;
  } | null;
}

export const demoIncident = {
  id: 'plan-demo-042',
  packetId: 'q3-executive-review',
  runId: 'run-demo-042',
  status: 'verified',
  source: 'demo',
  headline: 'One number changed. Nine consequences repaired.',
  summary:
    'A registered Sheet value moved from 4% to 9%. Veritas repaired only owned claim anchors and preserved the CFO paragraph.',
  detectedAt: '2026-08-21T10:42:07Z',
  updatedAt: '2026-08-21T10:42:16Z',
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
      action: 'Update the task title and decision note',
      guardrail: 'If-Match ETag',
      result: 'updated',
    },
  ],
  timeline: [
    {
      time: '10:42:07',
      occurredAt: '2026-08-21T10:42:07Z',
      label: 'Detected',
      detail: 'Sheet delta accepted',
      receipt: '91d80ce09d5241b7',
    },
    {
      time: '10:42:08',
      occurredAt: '2026-08-21T10:42:08Z',
      label: 'Traced',
      detail: '9 lineage paths',
      receipt: '424deea2d6db9f1c',
    },
    {
      time: '10:42:10',
      occurredAt: '2026-08-21T10:42:10Z',
      label: 'Approved',
      detail: '2 human decisions',
      receipt: '82e263c194f5fd06',
    },
    {
      time: '10:42:13',
      occurredAt: '2026-08-21T10:42:13Z',
      label: 'Repaired',
      detail: '9 terminal steps',
      receipt: '8371c586ed969c2a',
    },
    {
      time: '10:42:15',
      occurredAt: '2026-08-21T10:42:15Z',
      label: 'Verified',
      detail: '36 checks passed',
      receipt: 'd832adee23ef22a9',
    },
    {
      time: '10:42:16',
      occurredAt: '2026-08-21T10:42:16Z',
      label: 'Certified',
      detail: 'Scoped record issued',
      receipt: '2c3329983119174a',
    },
  ],
  coverage: {
    claims: 8,
    affectedClaims: 4,
    targets: 13,
    verifiedTargets: 13,
    protectedArtifacts: 5,
    verifiedProtectedArtifacts: 5,
    sources: 6,
    lineagePaths: 9,
  },
  certificate: {
    shortId: 'CERT-7A92',
    statement:
      'All monitored claims in this Decision Packet are consistent with their registered evidence versions as of the stated timestamp.',
    issuedAt: '2026-08-21T10:42:16Z',
  },
  checks: [
    {
      label: 'Repair run terminal',
      detail: '9 of 9 planned steps succeeded',
      receipt: 'run·e1c4',
      passed: true,
    },
    {
      label: 'Source set fresh',
      detail: '6 causal snapshots are still current',
      receipt: 'src·d09f',
      passed: true,
    },
    {
      label: 'Claims recomputed',
      detail: '8 deterministic recipes reproduced',
      receipt: 'clm·a881',
      passed: true,
    },
    {
      label: 'Targets re-read',
      detail: '13 Workspace targets match',
      receipt: 'tgt·29b3',
      passed: true,
    },
    {
      label: 'Human work preserved',
      detail: '5 protected projections unchanged',
      receipt: 'hsh·c443',
      passed: true,
    },
    {
      label: 'Correction drafts present',
      detail: '2 corrections independently read',
      receipt: 'drf·8d2a',
      passed: true,
    },
    {
      label: 'Coverage complete',
      detail: '0 candidate edges entered scope',
      receipt: 'cov·1000',
      passed: true,
    },
  ],
  evidence: [
    {
      id: 'churn',
      label: 'Customer churn',
      kind: 'Google Sheets',
      anchor: 'Metrics!B17',
      version: 'sheet-v2',
      snapshot: 'snap·3a91',
      snapshotId: 'snapshot-src-churn-v2-3a91',
      contentHash: '9f9ccf840b318ea42e3e1f585456b0f7d4cf3477e34369316bfd011672049d4c',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: true,
      current: true,
    },
    {
      id: 'previous-churn',
      label: 'Previous churn',
      kind: 'Google Sheets',
      anchor: 'Metrics!B16',
      version: 'sheet-v1',
      snapshot: 'snap·c882',
      snapshotId: 'snapshot-src-previous-churn-v1-c882',
      contentHash: '3128b83b80da6880bdaed72c3506f443888aeb55dd1a52d603eba292018a5049',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: false,
      current: true,
    },
    {
      id: 'revenue',
      label: 'Q3 revenue',
      kind: 'Google Sheets',
      anchor: 'Metrics!B5',
      version: 'sheet-v1',
      snapshot: 'snap·f230',
      snapshotId: 'snapshot-src-revenue-v1-f230',
      contentHash: '0e3a1940b4aa9f54bba6bb6f503e955029062f44dc1e28e4826e92c0594d9e44',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: false,
      current: true,
    },
    {
      id: 'pipeline',
      label: 'Qualified pipeline',
      kind: 'Google Sheets',
      anchor: 'Metrics!B8',
      version: 'sheet-v1',
      snapshot: 'snap·b122',
      snapshotId: 'snapshot-src-pipeline-v1-b122',
      contentHash: '0ab5a32cae09d3a0b325f62ddf45ded0abe78cacc85895c7bd96a0726a573ea4',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: false,
      current: true,
    },
    {
      id: 'nps',
      label: 'Net Promoter Score',
      kind: 'Google Sheets',
      anchor: 'Metrics!B20',
      version: 'sheet-v1',
      snapshot: 'snap·4cc9',
      snapshotId: 'snapshot-src-nps-v1-4cc9',
      contentHash: '8d91f9e05f17015d669bb4a7a30524b6f27fc5da2dc368287c62b8ab2d6d5705',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: false,
      current: true,
    },
    {
      id: 'launch',
      label: 'Launch date',
      kind: 'Google Docs',
      anchor: 'launch-date',
      version: 'doc-v1',
      snapshot: 'snap·71dd',
      snapshotId: 'snapshot-src-launch-v1-71dd',
      contentHash: 'e6c2a09a8634de5668564279aab64550b3a17e4259a8abb58d29a4231ae3a190',
      capturedAt: '2026-08-21T10:42:07Z',
      changed: false,
      current: true,
    },
  ],
  approvals: [],
  agentReview: {
    model: 'gemini-2.5-flash',
    disposition: 'proceed',
    rationale:
      'Registered scope and deterministic policy are coherent; proceed within the declared authority boundaries.',
    riskFlags: ['human approval required for decision-changing claims'],
    receipt: 'a1f94e0c2b',
  },
} as const satisfies Incident;
