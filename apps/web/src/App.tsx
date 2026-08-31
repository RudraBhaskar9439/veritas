import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import generationRequest from '../../../fixtures/demo/q3-generation-request.json';
import {
  type ClaimChange,
  demoIncident,
  type Incident,
  type IncidentApproval,
  type ViewId,
} from './incident';

const VIEW_STORAGE_KEY = 'veritas.command-center.view';
const CLAIM_STORAGE_KEY = 'veritas.command-center.claim';
const OPENING_SESSION_KEY = 'veritas.command-center.opening-seen';

type StartupStatus = 'loading' | 'ready' | 'unauthorized' | 'empty' | 'error';
type VerificationRetryState = 'idle' | 'running' | 'error';

interface PacketResource {
  artifactId?: string;
  sourceId?: string;
  kind: 'google_doc' | 'google_slides' | 'gmail' | 'google_task' | 'google_sheet';
  resourceId: string;
}

interface PacketGenerationResult {
  manifest: {
    packetId: string;
    artifacts: ReadonlyArray<PacketResource>;
    sources: ReadonlyArray<PacketResource>;
  };
  checksum: string;
  reused: boolean;
}

interface DeadLetterSummary {
  operationId: string;
  kind: string;
  correlationId: string;
  attempt: number;
  maxAttempts: number;
  errorCode: string;
  diagnosticFingerprint: string;
  replayOf: string | null;
  packetIds: ReadonlyArray<string>;
  updatedAt: string;
}

interface EmailTaskRoute {
  claimId: string;
  claimStatement: string;
  claimRisk: string;
  artifactId: string;
  taskId: string;
  taskListId: string;
}

interface EmailTaskWorkflow {
  workflowId: string;
  mailboxEmail: string;
  authorizedSender: string;
  packetId: string;
  claimId: string;
  artifactId: string;
  taskId: string;
  taskListId: string;
  status: 'active' | 'paused';
  createdAt: string;
  updatedAt: string;
}

interface EmailTaskThreadBinding {
  bindingId: string;
  workflowId: string;
  gmailThreadId: string;
  bootstrapMessageId: string | null;
  subjectLine: string;
  source: 'company_started' | 'operator_bound';
  createdAt: string;
  updatedAt: string;
}

interface EmailTaskUnmatchedRequest {
  requestId: string;
  gmailMessageId: string;
  gmailThreadId: string;
  mailboxEmail: string;
  sender: string;
  recipient: string;
  subjectLine: string;
  bodyHash: string;
  candidateWorkflowIds: ReadonlyArray<string>;
  status: 'pending' | 'bound';
  boundWorkflowId: string | null;
  receiptChecksum: string;
  receivedAt: string;
  createdAt: string;
  updatedAt: string;
}

interface EmailTaskSetup {
  packetId: string;
  mailboxEmail: string;
  routes: ReadonlyArray<EmailTaskRoute>;
  workflows: ReadonlyArray<EmailTaskWorkflow>;
  threads: ReadonlyArray<EmailTaskThreadBinding>;
  unmatchedRequests: ReadonlyArray<EmailTaskUnmatchedRequest>;
}

interface EmailTaskEvent {
  eventId: string;
  workflowId: string;
  gmailMessageId: string;
  sender: string;
  subjectLine: string;
  bodyHash: string;
  proposedTitle: string | null;
  proposedNote: string | null;
  status: 'received' | 'ignored' | 'escalated' | 'reviewing' | 'rejected' | 'applied';
  rationale: string;
  riskFlags: ReadonlyArray<string>;
  taskRevision: string | null;
  receiptChecksum: string;
  reviewDecision: 'approve' | 'reject' | null;
  reviewRequestId: string | null;
  reviewReason: string | null;
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewReceiptChecksum: string | null;
  receivedAt: string;
}

type LiveGenerationRequest = typeof generationRequest;

type GenerationState =
  | { phase: 'idle' }
  | { phase: 'running' }
  | { phase: 'error'; message: string; request: LiveGenerationRequest }
  | { phase: 'complete'; result: PacketGenerationResult; request: LiveGenerationRequest };

const views: ReadonlyArray<{
  id: ViewId;
  label: string;
  index: string;
  group: 'Operate' | 'Inspect';
  summary: string;
}> = [
  {
    id: 'overview',
    label: 'Command center',
    index: '01',
    group: 'Operate',
    summary: 'Incident outcome and the shortest route through the proof.',
  },
  {
    id: 'execution',
    label: 'Live run',
    index: '02',
    group: 'Operate',
    summary: 'Streaming receipts, causal graph, and change proof.',
  },
  {
    id: 'automation',
    label: 'Email → Task',
    index: '03',
    group: 'Operate',
    summary: 'Private Gmail thread routing and exact Task ownership.',
  },
  {
    id: 'decisions',
    label: 'Repair desk',
    index: '04',
    group: 'Operate',
    summary: 'Typed repair plan, approvals, conflicts, and recovery.',
  },
  {
    id: 'lineage',
    label: 'Blast radius',
    index: '05',
    group: 'Inspect',
    summary: 'Exact registered evidence-to-artifact paths.',
  },
  {
    id: 'proof',
    label: 'Proof ledger',
    index: '06',
    group: 'Inspect',
    summary: 'Native resource links, revisions, hashes, and claim diffs.',
  },
  {
    id: 'verification',
    label: 'Verification',
    index: '07',
    group: 'Inspect',
    summary: 'Independent checks and the scoped certificate.',
  },
  {
    id: 'architecture',
    label: 'Architecture',
    index: '08',
    group: 'Inspect',
    summary: 'Google Cloud trust boundaries and durable state.',
  },
];

function viewFromHash(): ViewId | null {
  const value = window.location.hash.replace(/^#\/?/, '');
  return views.some((view) => view.id === value) ? (value as ViewId) : null;
}

function storedView(): ViewId {
  const routed = viewFromHash();
  if (routed) return routed;
  const value = window.localStorage.getItem(VIEW_STORAGE_KEY);
  return views.some((view) => view.id === value) ? (value as ViewId) : 'overview';
}

function storedClaim(incident: Incident): string {
  const value = window.localStorage.getItem(CLAIM_STORAGE_KEY);
  return incident.claims.some((claim) => claim.id === value)
    ? (value ?? '')
    : incident.claims[0].id;
}

const IncidentContext = createContext<Incident | null>(null);

function useIncident(): Incident {
  const incident = useContext(IncidentContext);
  if (!incident) throw new Error('Incident context is unavailable');
  return incident;
}

function changedEvidence(incident: Incident) {
  return incident.evidence.find((source) => source.changed) ?? incident.evidence[0];
}

function displayScalar(statement: string | undefined): string | null {
  if (!statement) return null;
  const date = statement.match(/\b\d{4}-\d{2}-\d{2}\b/);
  if (date) return date[0];
  const percent = statement.match(/-?\d+(?:\.\d+)?\s*%/);
  if (percent) return percent[0].replace(/\s+/g, '');
  const currency = statement.match(/[$€£₹]\s*\d+(?:[.,]\d+)*(?:\s*[KMB])?/i);
  if (currency) return currency[0].replace(/\s+/g, '');
  const number = statement.match(/(?<![A-Za-z])-?\d+(?:\.\d+)?(?:\s*[KMB])?(?![A-Za-z])/i);
  return number?.[0].replace(/\s+/g, '') ?? null;
}

function primaryValueChange(incident: Incident): ClaimChange | undefined {
  return incident.claims.find((claim) => {
    const before = displayScalar(claim.before);
    const after = displayScalar(claim.after);
    return before !== null && after !== null && before !== after;
  });
}

function sourceTransitionValues(incident: Incident): { before: string; after: string } {
  const claim = primaryValueChange(incident);
  if (!claim) return { before: 'prior', after: 'current' };
  return {
    before: displayScalar(claim.before) ?? 'prior',
    after: displayScalar(claim.after) ?? 'current',
  };
}

function fullUtc(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace('.000Z', 'Z');
}

function elapsedLabel(start: string, end: string): string {
  const elapsedSeconds = Math.max(
    0,
    Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000),
  );
  if (!Number.isFinite(elapsedSeconds)) return 'Timing unavailable';
  if (elapsedSeconds < 60) return `${elapsedSeconds}s`;
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  return `${minutes}m ${seconds}s`;
}

function incidentLabel(incident: Incident): string {
  const suffix = incident.id
    .replace(/[^a-z0-9]/gi, '')
    .slice(-6)
    .toUpperCase();
  return suffix ? `INCIDENT ${suffix}` : 'INCIDENT';
}

function shouldPlayOpening(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.sessionStorage.getItem(OPENING_SESSION_KEY) !== 'true';
  } catch {
    return true;
  }
}

function OpeningSequence({ onComplete }: { onComplete: () => void }) {
  const [exiting, setExiting] = useState(false);
  const completed = useRef(false);

  const finish = useCallback(() => {
    if (completed.current) return;
    completed.current = true;
    try {
      window.sessionStorage.setItem(OPENING_SESSION_KEY, 'true');
    } catch {
      // Private browsing may disable storage; the animation can still finish.
    }
    onComplete();
  }, [onComplete]);

  function skip() {
    setExiting(true);
    window.setTimeout(finish, 320);
  }

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const beginExit = window.setTimeout(() => setExiting(true), 3300);
    const complete = window.setTimeout(finish, 3880);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(beginExit);
      window.clearTimeout(complete);
    };
  }, [finish]);

  return (
    <section
      className="openingSequence"
      data-exiting={exiting}
      aria-label="Veritas introduction"
      aria-modal="true"
      role="dialog"
    >
      <div className="openingGrid" aria-hidden="true" />
      <div className="openingAura" aria-hidden="true" />

      <header className="openingBrand">
        <span className="openingMark" aria-hidden="true">
          V
        </span>
        <strong>VERITAS</strong>
        <span>CONTINUOUS EVIDENCE INTEGRITY</span>
      </header>

      <div className="openingCopy">
        <span className="openingKicker">AUTONOMOUS CONSEQUENCE REPAIR</span>
        <h1>
          <span>When evidence changes,</span>
          <strong>repair every consequence.</strong>
        </h1>
        <p>
          When source truth changes, Veritas repairs every registered consequence—and proves the
          result.
        </p>
      </div>

      <svg
        className="openingGraph"
        viewBox="0 0 1080 700"
        role="img"
        aria-label="Registered evidence flowing through claims into owned workspace artifacts"
      >
        <defs>
          <linearGradient id="openingEdge" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#35bd7e" stopOpacity="0.25" />
            <stop offset="0.55" stopColor="#72e2aa" stopOpacity="0.9" />
            <stop offset="1" stopColor="#35bd7e" stopOpacity="0.3" />
          </linearGradient>
          <filter id="openingGlow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="8" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g className="openingEdges">
          <path className="openingEdge openingEdgeSource" d="M150 350 C280 350 350 350 470 350" />
          <path className="openingEdge openingEdgeOne" d="M550 350 C680 350 710 130 875 130" />
          <path className="openingEdge openingEdgeTwo" d="M550 350 C690 350 735 280 875 280" />
          <path className="openingEdge openingEdgeThree" d="M550 350 C690 350 735 430 875 430" />
          <path className="openingEdge openingEdgeFour" d="M550 350 C680 350 710 580 875 580" />
        </g>

        <g className="openingNode openingNodeSource" transform="translate(150 350)">
          <circle r="56" />
          <text textAnchor="middle" dominantBaseline="middle">
            S
          </text>
          <text className="openingNodeLabel" y="92" textAnchor="middle">
            SOURCE
          </text>
        </g>
        <g className="openingNode openingNodeClaim" transform="translate(510 350)">
          <circle r="62" />
          <text textAnchor="middle" dominantBaseline="middle">
            C
          </text>
          <text className="openingNodeLabel" y="100" textAnchor="middle">
            CLAIM MANIFEST
          </text>
        </g>
        {[
          { y: 130, letter: 'D', label: 'DOCS' },
          { y: 280, letter: 'S', label: 'SLIDES' },
          { y: 430, letter: 'G', label: 'GMAIL' },
          { y: 580, letter: 'T', label: 'TASKS' },
        ].map((node, index) => (
          <g
            className={`openingNode openingNodeArtifact openingNodeArtifact${index + 1}`}
            transform={`translate(925 ${node.y})`}
            key={node.label}
          >
            <circle r="47" />
            <text textAnchor="middle" dominantBaseline="middle">
              {node.letter}
            </text>
            <text className="openingNodeLabel" y="78" textAnchor="middle">
              {node.label}
            </text>
          </g>
        ))}
        <circle className="openingSignal" r="9" filter="url(#openingGlow)" />
      </svg>

      <ol className="openingSteps" aria-label="Veritas integrity lifecycle">
        <li>
          <span>01</span>
          <strong>DETECT</strong>
        </li>
        <li>
          <span>02</span>
          <strong>TRACE</strong>
        </li>
        <li>
          <span>03</span>
          <strong>REPAIR</strong>
        </li>
        <li>
          <span>04</span>
          <strong>VERIFY</strong>
        </li>
      </ol>

      <button className="openingSkip" type="button" onClick={skip}>
        Skip intro
        <span aria-hidden="true">↗</span>
      </button>
    </section>
  );
}

export function App({ initialIncident }: { initialIncident?: Incident }) {
  const [incident, setIncident] = useState<Incident | null>(initialIncident ?? null);
  const [state, setState] = useState<StartupStatus>(initialIncident ? 'ready' : 'loading');
  const [generation, setGeneration] = useState<GenerationState>({ phase: 'idle' });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (initialIncident) return;
    const controller = new AbortController();
    setState('loading');
    fetch('/api/v1/command-center/incidents/latest', {
      credentials: 'include',
      headers: { Accept: 'application/json', 'X-Veritas-Load-Attempt': String(retry) },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 401) {
          setState('unauthorized');
          return;
        }
        if (!response.ok) throw new Error(`command_center_${response.status}`);
        const result = (await response.json()) as Incident | null;
        setIncident(result);
        setState(result ? 'ready' : 'empty');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState('error');
      });
    return () => controller.abort();
  }, [initialIncident, retry]);

  useEffect(() => {
    if (generation.phase !== 'complete' || state === 'ready') return;
    const packetId = generation.result.manifest.packetId;
    let disposed = false;
    let refreshing = false;
    const refresh = async () => {
      if (disposed || refreshing) return;
      refreshing = true;
      try {
        const response = await fetch('/api/v1/command-center/incidents/latest', {
          credentials: 'include',
          headers: { Accept: 'application/json', 'X-Veritas-Refresh': 'packet-watch' },
        });
        if (response.status === 401) {
          if (!disposed) setState('unauthorized');
          return;
        }
        if (!response.ok) return;
        const result = (await response.json()) as Incident | null;
        if (!disposed && result?.packetId === packetId) {
          setIncident(result);
          setState('ready');
        }
      } catch {
        // The packet links remain usable while a transient poll is retried.
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [generation, state]);

  async function generateLivePacket(request: typeof generationRequest) {
    setGeneration({ phase: 'running' });
    try {
      const bootstrapResponse = await fetch('/api/v1/evidence/bootstrap', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          requestId: `${request.requestId}-sources`,
          sources: request.sources,
        }),
      });
      if (bootstrapResponse.status === 401) {
        setState('unauthorized');
        setGeneration({ phase: 'idle' });
        return;
      }
      if (!bootstrapResponse.ok) throw new Error(await safeApiError(bootstrapResponse));
      const bootstrapped = (await bootstrapResponse.json()) as {
        sources: ReadonlyArray<PacketResource & { value: unknown }>;
      };
      const packetResponse = await fetch('/api/v1/packets', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ ...request, sources: bootstrapped.sources }),
      });
      if (!packetResponse.ok) throw new Error(await safeApiError(packetResponse));
      setGeneration({
        phase: 'complete',
        result: (await packetResponse.json()) as PacketGenerationResult,
        request,
      });
    } catch (error: unknown) {
      setGeneration({
        phase: 'error',
        message: error instanceof Error ? error.message : 'Live generation failed.',
        request,
      });
    }
  }

  function generateFreshLivePacket() {
    const suffix = crypto.randomUUID().replaceAll('-', '').slice(0, 12);
    const request: typeof generationRequest = {
      ...generationRequest,
      requestId: `${generationRequest.requestId}-${suffix}`,
      blueprint: {
        ...generationRequest.blueprint,
        packetId: `${generationRequest.blueprint.packetId}-${suffix}`,
      },
    };
    setIncident(null);
    setState('empty');
    void generateLivePacket(request);
  }

  if (state !== 'ready' || !incident) {
    return (
      <StartupState
        state={state}
        generation={generation}
        onGenerate={() =>
          void generateLivePacket(
            generation.phase === 'error' ? generation.request : generationRequest,
          )
        }
        onReplay={(request) => void generateLivePacket(request)}
        onRetry={() => setRetry((value) => value + 1)}
        onDemo={() => {
          setIncident(demoIncident);
          setState('ready');
        }}
      />
    );
  }
  return (
    <CommandCenter
      incident={incident}
      onIncidentChange={setIncident}
      onNewPacket={generateFreshLivePacket}
    />
  );
}

function CommandCenter({
  incident,
  onIncidentChange,
  onNewPacket,
}: {
  incident: Incident;
  onIncidentChange: (incident: Incident) => void;
  onNewPacket: () => void;
}) {
  const [isOpening, setIsOpening] = useState(shouldPlayOpening);
  const completeOpening = useCallback(() => setIsOpening(false), []);
  const [view, setView] = useState<ViewId>(storedView);
  const [selectedClaimId, setSelectedClaimId] = useState(() => storedClaim(incident));
  const [replayStage, setReplayStage] = useState<number>(incident.timeline.length);
  const [isReplaying, setIsReplaying] = useState(false);
  const [isLiveAnimating, setIsLiveAnimating] = useState(false);
  const [verificationRetry, setVerificationRetry] = useState<VerificationRetryState>('idle');
  const observedIncidentId = useRef(incident.id);
  const observedTimelineLength = useRef(incident.timeline.length);
  const selectedClaim =
    incident.claims.find((claim) => claim.id === selectedClaimId) ?? incident.claims[0];

  useEffect(() => {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
    window.scrollTo?.({ top: 0, behavior: 'auto' });
  }, [view]);

  useEffect(() => {
    const syncRoute = () => {
      const routed = viewFromHash();
      if (routed) setView(routed);
    };
    window.addEventListener('hashchange', syncRoute);
    window.addEventListener('popstate', syncRoute);
    return () => {
      window.removeEventListener('hashchange', syncRoute);
      window.removeEventListener('popstate', syncRoute);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(CLAIM_STORAGE_KEY, selectedClaimId);
  }, [selectedClaimId]);

  useEffect(() => {
    if (!isReplaying && !isLiveAnimating) return;
    const timer = window.setInterval(
      () => {
        setReplayStage((stage) => {
          const next = stage + 1;
          if (next >= incident.timeline.length) {
            setIsReplaying(false);
            setIsLiveAnimating(false);
            return incident.timeline.length;
          }
          return next;
        });
      },
      isReplaying ? 720 : 460,
    );
    return () => window.clearInterval(timer);
  }, [isLiveAnimating, isReplaying, incident.timeline.length]);

  useEffect(() => {
    const previousIncidentId = observedIncidentId.current;
    const previousTimelineLength = observedTimelineLength.current;
    const isNewIncident = previousIncidentId !== incident.id;
    const hasNewReceipts =
      previousIncidentId === incident.id && incident.timeline.length > previousTimelineLength;

    observedIncidentId.current = incident.id;
    observedTimelineLength.current = incident.timeline.length;

    if (isReplaying) return;
    if (incident.source === 'live' && (isNewIncident || hasNewReceipts)) {
      setReplayStage(isNewIncident ? 0 : previousTimelineLength);
      setIsLiveAnimating(incident.timeline.length > 0);
      return;
    }
    if (!isLiveAnimating) setReplayStage(incident.timeline.length);
  }, [incident.id, incident.source, incident.timeline.length, isLiveAnimating, isReplaying]);

  useEffect(() => {
    if (incident.source !== 'live') return;
    let disposed = false;
    let refreshing = false;
    const refresh = async () => {
      if (disposed || refreshing) return;
      refreshing = true;
      try {
        const response = await fetch('/api/v1/command-center/incidents/latest', {
          credentials: 'include',
          headers: { Accept: 'application/json', 'X-Veritas-Refresh': 'poll' },
        });
        if (!response.ok) return;
        const result = (await response.json()) as Incident | null;
        if (!disposed && result) onIncidentChange(result);
      } catch {
        // Keep the last authenticated incident visible through transient refresh failures.
      } finally {
        refreshing = false;
      }
    };
    const timer = window.setInterval(() => void refresh(), 3000);
    const onFocus = () => void refresh();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [incident.source, onIncidentChange]);

  function chooseView(next: ViewId) {
    setView(next);
    const hash = `#/${next}`;
    if (window.location.hash !== hash) {
      window.history.pushState({ view: next }, '', hash);
    }
  }

  function replayIncident() {
    setIsLiveAnimating(false);
    setReplayStage(0);
    setIsReplaying(true);
    chooseView('execution');
  }

  async function retryVerification() {
    if (incident.source !== 'live' || !incident.runId || incident.certificate) return;
    setVerificationRetry('running');
    try {
      const response = await fetch(
        `/api/v1/repair-runs/${encodeURIComponent(incident.runId)}/verify`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ requestId: crypto.randomUUID() }),
        },
      );
      if (!response.ok) throw new Error(`verification_${response.status}`);
      const refreshed = await fetch('/api/v1/command-center/incidents/latest', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!refreshed.ok) throw new Error(`refresh_${refreshed.status}`);
      const result = (await refreshed.json()) as Incident | null;
      if (!result) throw new Error('incident_missing');
      onIncidentChange(result);
      setVerificationRetry('idle');
    } catch {
      setVerificationRetry('error');
    }
  }

  const visibleClaims = replayStage >= 2 ? incident.claims.length : 0;
  const visibleArtifacts = replayStage >= 3 ? incident.artifacts.length : 0;
  const verifiedTargets = replayStage >= 4 ? incident.coverage.verifiedTargets : 0;

  return (
    <IncidentContext.Provider value={incident}>
      {isOpening && <OpeningSequence onComplete={completeOpening} />}
      <div className="appFrame">
        <a className="skipLink" href="#main-content">
          Skip to incident details
        </a>

        <header className="topbar">
          <a className="brand" href="#/overview" aria-label="Veritas command center home">
            <span className="brandMark" aria-hidden="true">
              V
            </span>
            <span className="brandWord">VERITAS</span>
            <span className="brandDescriptor">Autonomous consequence repair</span>
          </a>
          <div className="topbarActions">
            <span className="environment">
              {incident.source === 'live'
                ? 'Live Workspace evidence'
                : 'Offline evidence-bound demo'}
            </span>
            <span className="systemStatus">
              <span className="pulseDot" aria-hidden="true" />
              {incident.status.replace('_', ' ')}
            </span>
            <button className="introReplayButton" type="button" onClick={() => setIsOpening(true)}>
              <span aria-hidden="true">✦</span>
              Opening
            </button>
            <button className="replayButton" type="button" onClick={replayIncident}>
              <span aria-hidden="true">↻</span>
              {isReplaying ? 'Replaying incident' : 'Replay incident'}
            </button>
            {incident.source === 'live' && (
              <button className="replayButton" type="button" onClick={onNewPacket}>
                <span aria-hidden="true">＋</span>
                New monitored packet
              </button>
            )}
          </div>
        </header>

        <aside className="sidebar" aria-label="Incident views">
          <div className="incidentIdentity">
            <span className="incidentMonogram" aria-hidden="true">
              Q3
            </span>
            <div>
              <span className="sidebarLabel">Decision packet</span>
              <strong>Executive review</strong>
              <span className="incidentDuration">
                {incident.status === 'verified'
                  ? `Certified after ${elapsedLabel(incident.detectedAt, incident.updatedAt)}`
                  : `Open for ${elapsedLabel(incident.detectedAt, incident.updatedAt)}`}
              </span>
            </div>
          </div>
          <nav aria-label="Veritas destinations">
            {(['Operate', 'Inspect'] as const).map((group) => (
              <div className="navGroup" key={group}>
                <span className="navGroupLabel">{group}</span>
                {views
                  .filter((item) => item.group === group)
                  .map((item) => (
                    <button
                      className="navItem"
                      data-active={view === item.id}
                      key={item.id}
                      type="button"
                      onClick={() => chooseView(item.id)}
                      aria-current={view === item.id ? 'page' : undefined}
                    >
                      <span>{item.index}</span>
                      {item.label}
                    </button>
                  ))}
              </div>
            ))}
          </nav>
          <div className="sidebarFooter">
            <span className="sidebarLabel">Integrity window</span>
            <strong>{fullUtc(incident.detectedAt)}</strong>
            <span>{incident.coverage.sources} immutable evidence versions</span>
          </div>
        </aside>

        <main id="main-content" className="mainContent" tabIndex={-1}>
          <nav className="mobileNav" aria-label="Incident views">
            {views.map((item) => (
              <button
                data-active={view === item.id}
                key={item.id}
                type="button"
                onClick={() => chooseView(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>

          {view === 'overview' && (
            <Overview
              replayStage={replayStage}
              visibleClaims={visibleClaims}
              visibleArtifacts={visibleArtifacts}
              verifiedTargets={verifiedTargets}
              onNavigate={chooseView}
            />
          )}
          {view === 'execution' && (
            <ExecutionView replayStage={replayStage} isStreaming={isReplaying || isLiveAnimating} />
          )}
          {view === 'automation' && <AutomationView />}
          {view === 'decisions' && <DecisionsView onIncidentChange={onIncidentChange} />}
          {view === 'lineage' && <LineageView />}
          {view === 'proof' && (
            <ProofView selectedClaim={selectedClaim} onSelectClaim={setSelectedClaimId} />
          )}
          {view === 'verification' && (
            <VerificationView
              onRetryVerification={() => void retryVerification()}
              verificationRetry={verificationRetry}
            />
          )}
          {view === 'architecture' && <ArchitectureView />}
        </main>

        <div className="srOnly" role="status" aria-live="polite">
          {isReplaying
            ? `Incident replay step ${replayStage + 1} of ${incident.timeline.length}`
            : incident.status === 'verified'
              ? 'Incident is independently verified.'
              : incident.status === 'attention'
                ? 'Incident requires operator attention before verification.'
                : incident.status === 'awaiting_approval'
                  ? 'Incident is waiting for human approval before verification.'
                  : 'Incident repair is in progress.'}
        </div>
      </div>
    </IncidentContext.Provider>
  );
}

function StartupState({
  state,
  generation,
  onGenerate,
  onReplay,
  onRetry,
  onDemo,
}: {
  state: StartupStatus;
  generation: GenerationState;
  onGenerate: () => void;
  onReplay: (request: LiveGenerationRequest) => void;
  onRetry: () => void;
  onDemo: () => void;
}) {
  const connect = () => {
    window.location.assign('/api/v1/auth/google/start?returnTo=/');
  };
  const title =
    state === 'loading'
      ? 'Loading your evidence boundary…'
      : state === 'unauthorized'
        ? 'Connect Google Workspace to begin.'
        : state === 'empty'
          ? 'Your workspace is connected.'
          : 'The live Command Center is temporarily unreachable.';
  const connectionTitle =
    state === 'loading'
      ? 'Establishing a secure session'
      : state === 'unauthorized'
        ? 'Authorize the evidence boundary'
        : state === 'empty'
          ? 'Create your monitored packet'
          : 'Restore the production connection';
  return (
    <main className="startupState" data-state={state}>
      <div className="startupGrid" aria-hidden="true" />
      <header className="startupHeader">
        <div className="startupBrand">
          <span className="brandMark" aria-hidden="true">
            V
          </span>
          <strong>VERITAS</strong>
          <span>Autonomous consequence repair</span>
        </div>
        <div className="startupEnvironment">
          <i aria-hidden="true" />
          Google Cloud production runtime
        </div>
      </header>

      <div className="startupLayout">
        <section className="startupNarrative" aria-labelledby="startup-title">
          <span className="sectionKicker">Production evidence boundary</span>
          <h1 id="startup-title">{title}</h1>
          <p>
            {state === 'empty'
              ? 'Generate a decision packet to register its claims, evidence, and downstream artifacts.'
              : 'Veritas watches registered evidence, repairs only owned consequences, preserves human authorship, and independently verifies the result.'}
          </p>
          <ul className="startupProofs" aria-label="Veritas trust guarantees">
            <li>
              <span>01</span>
              <strong>Exact lineage</strong>
              <small>No inferred writes</small>
            </li>
            <li>
              <span>02</span>
              <strong>Human authority</strong>
              <small>Decisions pause safely</small>
            </li>
            <li>
              <span>03</span>
              <strong>Independent proof</strong>
              <small>The worker cannot certify itself</small>
            </li>
          </ul>
        </section>

        <section className="startupConnectCard" aria-labelledby="connection-title">
          <div className="startupCardTopline">
            <span>Workspace connection</span>
            <span className="startupConnectionStatus" data-active={state === 'empty'}>
              <i aria-hidden="true" />
              {state === 'empty' ? 'connected' : state === 'loading' ? 'checking' : 'not connected'}
            </span>
          </div>
          <div className="workspaceGlyph" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <strong>W</strong>
          </div>
          <span className="sectionKicker">Google Workspace</span>
          <h2 id="connection-title">{connectionTitle}</h2>
          <p>
            Subject-scoped OAuth gives Veritas access only to the Workspace resources registered in
            your decision packet.
          </p>

          <div className="startupActions">
            {state === 'unauthorized' && (
              <button className="primaryButton" type="button" onClick={connect}>
                Connect Google Workspace <span aria-hidden="true">↗</span>
              </button>
            )}
            {(state === 'error' || state === 'empty') && (
              <button className="replayButton" type="button" onClick={onRetry}>
                Retry live data
              </button>
            )}
            {state === 'empty' && generation.phase !== 'complete' && (
              <button
                className="primaryButton"
                type="button"
                onClick={onGenerate}
                disabled={generation.phase === 'running'}
              >
                {generation.phase === 'running'
                  ? 'Creating real Workspace packet…'
                  : 'Generate real Workspace packet'}
              </button>
            )}
            {state !== 'loading' && (
              <button className="secondaryButton" type="button" onClick={onDemo}>
                Open offline judge demo
              </button>
            )}
          </div>

          <dl className="startupTrustFacts">
            <div>
              <dt>Identity</dt>
              <dd>Subject-scoped OAuth</dd>
            </div>
            <div>
              <dt>Writes</dt>
              <dd>Manifest-bound only</dd>
            </div>
            <div>
              <dt>Fallback</dt>
              <dd>Never silent</dd>
            </div>
          </dl>
        </section>
      </div>

      {(generation.phase === 'error' || generation.phase === 'complete') && (
        <div className="startupResultZone">
          {generation.phase === 'error' && (
            <p className="actionError" role="alert">
              {generation.message} No demonstration data was substituted.
            </p>
          )}
          {generation.phase === 'complete' && (
            <GeneratedPacket
              result={generation.result}
              onRetry={() => onReplay(generation.request)}
            />
          )}
        </div>
      )}

      <footer className="startupFooter">
        <span>Gemini 3.5 Flash</span>
        <span>Google Gen AI SDK</span>
        <span>Cloud Run</span>
        <span>Independent verifier</span>
      </footer>
    </main>
  );
}

async function safeApiError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string' && payload.detail.length <= 240) {
      return payload.detail;
    }
  } catch {
    // A bounded status message remains available when an upstream response is not JSON.
  }
  return `Live Workspace request failed with status ${response.status}.`;
}

function GeneratedPacket({
  result,
  onRetry,
}: {
  result: PacketGenerationResult;
  onRetry: () => void;
}) {
  const resources = [...result.manifest.sources, ...result.manifest.artifacts];
  return (
    <section className="generatedPacket" aria-labelledby="generated-title">
      <span className="sectionKicker">Live Workspace proof</span>
      <h2 id="generated-title">Decision packet created and monitored.</h2>
      <p>
        The source Sheet, policy Doc, five downstream artifacts, registered lineage, and Drive
        change watch now use real Google resource IDs.
      </p>
      <p className="monitoringStatus" role="status">
        {result.reused
          ? 'Idempotent replay confirmed · no duplicate Workspace artifacts were created.'
          : 'Live monitoring active · waiting for a meaningful source change.'}
      </p>
      <div className="generatedLinks">
        {resources.map((resource) => {
          const url = workspaceResourceUrl(resource);
          const label = resource.sourceId ?? resource.artifactId ?? resource.kind;
          return url ? (
            <a
              key={`${resource.kind}:${resource.resourceId}`}
              href={url}
              target="_blank"
              rel="noreferrer"
            >
              <span>{resource.kind.replace('google_', '').replace('_', ' ')}</span>
              <strong>{label}</strong>
              <small>Open real artifact ↗</small>
            </a>
          ) : null;
        })}
      </div>
      <div className="startupActions">
        <button className="secondaryButton" type="button" onClick={onRetry}>
          Verify idempotent replay
        </button>
      </div>
    </section>
  );
}

function workspaceResourceUrl(resource: PacketResource): string | null {
  if (resource.kind === 'google_sheet') {
    return `https://docs.google.com/spreadsheets/d/${resource.resourceId}/edit`;
  }
  if (resource.kind === 'google_doc') {
    return `https://docs.google.com/document/d/${resource.resourceId}/edit`;
  }
  if (resource.kind === 'google_slides') {
    return `https://docs.google.com/presentation/d/${resource.resourceId}/edit`;
  }
  if (resource.kind === 'gmail') {
    return `https://mail.google.com/mail/u/0/#drafts/${resource.resourceId}`;
  }
  if (resource.kind === 'google_task') {
    return 'https://tasks.google.com/';
  }
  return null;
}

interface OverviewProps {
  replayStage: number;
  visibleClaims: number;
  visibleArtifacts: number;
  verifiedTargets: number;
  onNavigate: (view: ViewId) => void;
}

function Overview({
  replayStage,
  visibleClaims,
  visibleArtifacts,
  verifiedTargets,
  onNavigate,
}: OverviewProps) {
  const incident = useIncident();
  const source = changedEvidence(incident);
  const { before: beforeValue, after: afterValue } = sourceTransitionValues(incident);
  return (
    <>
      <section className="judgeStage" aria-labelledby="incident-title">
        <div className="stageGrid" aria-hidden="true" />
        <div className="incidentHeading">
          <div className="incidentMeta">
            <span className="incidentNumber">AUTONOMOUS RUN · {incidentLabel(incident)}</span>
            <span className="severity">Material evidence change</span>
          </div>
          <h1 id="incident-title">{incident.headline}</h1>
          <p>{incident.summary}</p>
          <ul className="heroProofRow" aria-label="Run guarantees">
            <li>
              <i aria-hidden="true">01</i> No prompt after source change
            </li>
            <li>
              <i aria-hidden="true">02</i> Human prose hash-preserved
            </li>
            <li>
              <i aria-hidden="true">03</i> Independently re-read
            </li>
          </ul>
        </div>

        <div className="sourceShiftCard" data-visible={replayStage >= 1}>
          <div className="sourceCardTopline">
            <span className="sourceApp">
              <i aria-hidden="true">S</i> {source?.kind ?? 'Registered evidence'}
            </span>
            <span className="sourceLive">
              <i aria-hidden="true" /> source event
            </span>
          </div>
          <div className="sourceAnchor">
            <span>REGISTERED SOURCE</span>
            <code>{source?.anchor ?? 'registered anchor'}</code>
          </div>
          <div className="valueTransition">
            <span className="srOnly">
              The registered source value changed; exact claim diffs follow
            </span>
            <s>{beforeValue}</s>
            <span aria-hidden="true">→</span>
            <strong>{afterValue}</strong>
          </div>
          <div className="sourceClock">
            <span>
              <small>Detected</small>
              {incident.timeline[0]?.time ?? 'pending'}
            </span>
            <span>
              <small>Updated</small>
              {incident.timeline.at(-1)?.time ?? 'pending'}
            </span>
          </div>
          {incident.agentReview && (
            <section className="agentReceipt" aria-label="Gemini agent review">
              <span>G</span>
              <div>
                <strong>{incident.agentReview.model}</strong>
                <small>
                  {incident.agentReview.disposition} · {incident.agentReview.receipt}
                </small>
              </div>
            </section>
          )}
          <div className="scopeStamp" data-visible={replayStage >= 5}>
            <span aria-hidden="true">✓</span>
            <div>
              <strong>
                {incident.certificate ? 'Scoped certificate issued' : 'Integrity gate pending'}
              </strong>
              <small>
                {incident.certificate?.shortId ?? incident.status.replace('_', ' ')} ·{' '}
                {incident.checks.length} checks
              </small>
            </div>
          </div>
        </div>
      </section>

      <section className="metricStrip" aria-label="Incident outcome">
        <Metric
          value={`${visibleClaims}`}
          label="Claims changed"
          detail={`of ${incident.coverage.claims} monitored`}
        />
        <Metric
          value={`${visibleArtifacts}`}
          label="Artifacts repaired"
          detail="across Workspace"
        />
        <Metric
          value={`${verifiedTargets}/${incident.coverage.targets}`}
          label="Targets verified"
          detail="independent re-read"
        />
        <Metric value="0" label="Human edits lost" detail="protected by hash" accent />
      </section>
      <RouteDirectory onNavigate={onNavigate} />
    </>
  );
}

function routeStatus(incident: Incident, view: ViewId): string {
  const pendingApprovals = incident.approvals.filter(
    (approval) => approval.status === 'pending',
  ).length;
  if (view === 'execution') return `${incident.timeline.length} signed receipts`;
  if (view === 'automation')
    return incident.source === 'live' ? 'Workspace route ready' : 'Live only';
  if (view === 'decisions') {
    return incident.status === 'attention'
      ? 'Operator attention'
      : `${pendingApprovals} decision${pendingApprovals === 1 ? '' : 's'} pending`;
  }
  if (view === 'lineage') return `${incident.coverage.lineagePaths} exact paths`;
  if (view === 'proof') return `${incident.artifacts.length} native artifacts`;
  if (view === 'verification') {
    return incident.certificate
      ? `${incident.coverage.verifiedTargets}/${incident.coverage.targets} certified`
      : 'Certificate gated';
  }
  if (view === 'architecture') return '8 production boundaries';
  return incident.status.replace('_', ' ');
}

function RouteDirectory({ onNavigate }: { onNavigate: (view: ViewId) => void }) {
  const incident = useIncident();
  return (
    <section className="routeDirectory" aria-labelledby="route-directory-title">
      <div className="routeDirectoryHeader">
        <div>
          <span className="sectionKicker">Judge navigation</span>
          <h2 id="route-directory-title">Go straight to the proof you want.</h2>
        </div>
        <p>No long-page hunting. Every capability now has its own destination.</p>
      </div>
      <div className="routeCardGrid">
        {views
          .filter((item) => item.id !== 'overview')
          .map((item) => (
            <button
              className="routeCard"
              type="button"
              key={item.id}
              onClick={() => onNavigate(item.id)}
            >
              <span className="routeCardIndex">{item.index}</span>
              <span className="routeCardGroup">{item.group}</span>
              <strong>{item.label}</strong>
              <small>{item.summary}</small>
              <span className="routeCardStatus">{routeStatus(incident, item.id)}</span>
              <i aria-hidden="true">→</i>
            </button>
          ))}
      </div>
    </section>
  );
}

function ExecutionView({
  replayStage,
  isStreaming,
}: {
  replayStage: number;
  isStreaming: boolean;
}) {
  return (
    <>
      <ViewHeader
        kicker="Autonomous execution"
        title="Every agent step appears as it happens."
        description="The live terminal, causal graph, timeline, timestamps, and cryptographic receipt chain update from persisted backend state without a page reload."
      />
      <RunProgressRibbon activeStage={replayStage} isStreaming={isStreaming} />
      <GeminiDecisionReceipt visible={replayStage >= 2} />
      <Timeline activeStage={replayStage} isStreaming={isStreaming} />
      <ChangeProofPanel />
    </>
  );
}

function AutomationView() {
  return (
    <>
      <ViewHeader
        kicker="Customer signal automation"
        title="A normal Gmail reply reaches one exact Google Task."
        description="The operator registers the customer and manifest-bound Task once. Veritas then routes only the private Gmail thread, refuses ambiguous requests, and records every Task revision."
      />
      <EmailTaskAutomation defaultOpen />
    </>
  );
}

function DecisionsView({ onIncidentChange }: { onIncidentChange: (incident: Incident) => void }) {
  return (
    <>
      <ViewHeader
        kicker="Repair and authority desk"
        title="See the plan, the guardrail, and who has authority."
        description="Automatic, approval-required, draft-only, and conflict-stopped work are separated before any native Workspace mutation is allowed."
      />
      <RepairPlanPanel />
      <AttentionRecoveryPanel />
      <ApprovalQueue onIncidentChange={onIncidentChange} />
      <RecoveryQueue onIncidentChange={onIncidentChange} />
      <RepairActivityPanel />
    </>
  );
}

function ProofView({
  selectedClaim,
  onSelectClaim,
}: {
  selectedClaim: ClaimChange;
  onSelectClaim: (claimId: string) => void;
}) {
  const incident = useIncident();
  return (
    <>
      <ViewHeader
        kicker="Native Workspace proof"
        title="Open the artifact. Inspect the revision. Follow the receipt."
        description="This ledger exposes the real resource boundary, minimum-write scope, native concurrency guard, preservation state, and deterministic claim diff."
      />
      <ConsequenceMap replayStage={incident.timeline.length} />
      <ArtifactProofLedger />
      <PreservationProofPanel />
      <ClaimDiffPanel selectedClaim={selectedClaim} onSelectClaim={onSelectClaim} />
    </>
  );
}

function repairLane(artifact: Incident['artifacts'][number]): {
  label: string;
  kind: 'automatic' | 'approval' | 'draft';
} {
  if (artifact.guardrail.toLowerCase().includes('human approved')) {
    return { label: 'Human approval', kind: 'approval' };
  }
  if (
    artifact.surface.toLowerCase().includes('gmail') ||
    artifact.guardrail.toLowerCase().includes('immutable')
  ) {
    return { label: 'Draft only', kind: 'draft' };
  }
  return { label: 'Automatic', kind: 'automatic' };
}

function RepairPlanPanel() {
  const incident = useIncident();
  const operationCount = incident.artifacts.reduce(
    (total, artifact) => total + artifact.targetCount,
    0,
  );
  const laneCounts = incident.artifacts.reduce(
    (counts, artifact) => {
      const lane = repairLane(artifact).kind;
      counts[lane] += artifact.targetCount;
      return counts;
    },
    { automatic: 0, approval: 0, draft: 0 },
  );
  const blocked = incident.artifacts.reduce(
    (total, artifact) => total + (artifact.result.includes('attention') ? artifact.targetCount : 0),
    0,
  );
  return (
    <section className="panel repairPlanPanel" aria-labelledby="repair-plan-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Typed repair plan</span>
          <h2 id="repair-plan-title">{operationCount} registered target operations</h2>
        </div>
        <span className="appendOnly">Policy checked</span>
      </div>
      <section className="planSummary" aria-label="Repair policy summary">
        <div>
          <strong>{laneCounts.automatic}</strong>
          <span>Automatic</span>
        </div>
        <div>
          <strong>{laneCounts.approval}</strong>
          <span>Approval required</span>
        </div>
        <div>
          <strong>{laneCounts.draft}</strong>
          <span>Draft only</span>
        </div>
        <div data-alert={blocked > 0}>
          <strong>{blocked}</strong>
          <span>Blocked by precondition</span>
        </div>
      </section>
      <ol className="typedPlanList">
        {incident.artifacts.map((artifact, index) => {
          const lane = repairLane(artifact);
          const attention = artifact.result.includes('attention');
          return (
            <li key={artifact.id}>
              <span className="planStep">{String(index + 1).padStart(2, '0')}</span>
              <span
                className={`surfaceIcon surface-${artifact.code.toLowerCase()}`}
                aria-hidden="true"
              >
                {artifact.code}
              </span>
              <div>
                <strong>{artifact.name}</strong>
                <span>{artifact.action}</span>
                <small>
                  {artifact.targetCount} exact target{artifact.targetCount === 1 ? '' : 's'} ·{' '}
                  {artifact.guardrail}
                </small>
              </div>
              <span className={`planLane lane-${lane.kind}`}>{lane.label}</span>
              <span className="planResult" data-attention={attention}>
                {artifact.result}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function AttentionRecoveryPanel() {
  const incident = useIncident();
  const conflicts = incident.artifacts.filter((artifact) => artifact.result.includes('attention'));
  const pendingApprovals = incident.approvals.filter(
    (approval) => approval.status === 'pending',
  ).length;
  return (
    <section className="panel recoveryStatusPanel" aria-labelledby="recovery-status-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Recovery visibility</span>
          <h2 id="recovery-status-title">
            {conflicts.length > 0
              ? 'A native revision conflict stopped the run safely.'
              : incident.status === 'verified'
                ? 'No recovery action is required.'
                : 'The durable run is progressing within policy.'}
          </h2>
        </div>
        <span className="severity">{conflicts.length > 0 ? 'Attention' : incident.status}</span>
      </div>
      <div className="recoverySpine">
        <article data-state={conflicts.length > 0 ? 'active' : 'complete'}>
          <span>01</span>
          <div>
            <strong>Native precondition</strong>
            <small>
              {conflicts.length > 0
                ? `${conflicts.map((artifact) => artifact.name).join(', ')} changed after planning; completed writes remain preserved.`
                : 'Every native write reached its expected revision boundary.'}
            </small>
          </div>
        </article>
        <article data-state={pendingApprovals > 0 ? 'waiting' : 'complete'}>
          <span>02</span>
          <div>
            <strong>Human authority</strong>
            <small>
              {pendingApprovals} decision{pendingApprovals === 1 ? '' : 's'} remain
              {pendingApprovals === 1 ? 's' : ''} pending.
            </small>
          </div>
        </article>
        <article data-state={incident.certificate ? 'complete' : 'waiting'}>
          <span>03</span>
          <div>
            <strong>Independent verification</strong>
            <small>
              {incident.certificate
                ? `${incident.coverage.verifiedTargets}/${incident.coverage.targets} targets certified.`
                : 'Starts only after repair and authority gates clear.'}
            </small>
          </div>
        </article>
      </div>
      {conflicts.length > 0 && (
        <p className="actionNotice">
          Veritas did not overwrite newer human or Workspace state. The conflict receipt is
          retained; reconciliation must produce a fresh, version-checked operation before
          verification can resume.
        </p>
      )}
    </section>
  );
}

function RepairActivityPanel() {
  const incident = useIncident();
  return (
    <section className="panel activityPanel" aria-labelledby="activity-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Auditable execution</span>
          <h2 id="activity-title">Every consequential action has a receipt</h2>
        </div>
        <span className="appendOnly">Append-only journal</span>
      </div>
      <div className="tableScroller">
        <table className="activityTable" aria-label="Repair activity">
          <thead>
            <tr>
              <th scope="col">Surface</th>
              <th scope="col">Minimal action</th>
              <th scope="col">Guardrail</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {incident.artifacts.map((artifact) => (
              <tr key={artifact.id}>
                <td>
                  <span className="artifactName">
                    <span
                      className={`surfaceIcon surface-${artifact.code.toLowerCase()}`}
                      aria-hidden="true"
                    >
                      {artifact.code}
                    </span>
                    <span>
                      <strong>{artifact.name}</strong>
                      <small>{artifact.targetCount} registered targets</small>
                    </span>
                  </span>
                </td>
                <td>{artifact.action}</td>
                <td>{artifact.guardrail}</td>
                <td>
                  <span className="successCell">
                    <span aria-hidden="true">✓</span> {artifact.result}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ArtifactProofLedger() {
  const incident = useIncident();
  return (
    <section className="panel artifactProofPanel" aria-labelledby="artifact-proof-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Artifact proof ledger</span>
          <h2 id="artifact-proof-title">
            {incident.artifacts.length} native surfaces, individually inspectable
          </h2>
        </div>
        <span className="appendOnly">Manifest bound</span>
      </div>
      <div className="artifactProofGrid">
        {incident.artifacts.map((artifact) => (
          <article key={artifact.id}>
            <div className="artifactProofTopline">
              <span
                className={`surfaceIcon surface-${artifact.code.toLowerCase()}`}
                aria-hidden="true"
              >
                {artifact.code}
              </span>
              <span>{artifact.surface}</span>
              <span data-attention={artifact.result.includes('attention')}>{artifact.result}</span>
            </div>
            <h3>{artifact.name}</h3>
            <p>{artifact.action}</p>
            <dl>
              <div>
                <dt>Resource</dt>
                <dd>
                  <code>{artifact.resourceId ?? artifact.id}</code>
                </dd>
              </div>
              <div>
                <dt>Native revision</dt>
                <dd>
                  <code>{artifact.baseRevisionId ?? artifact.guardrail}</code>
                </dd>
              </div>
              <div>
                <dt>Owned targets</dt>
                <dd>{artifact.targetCount}</dd>
              </div>
            </dl>
            {artifact.resourceUrl ? (
              <a
                className="artifactOpenLink"
                href={artifact.resourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open real {artifact.surface} artifact ↗
              </a>
            ) : (
              <span className="artifactLinkUnavailable">
                {incident.source === 'demo'
                  ? 'Offline demonstration record'
                  : 'Resource link awaiting API refresh'}
              </span>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function PreservationProofPanel() {
  const incident = useIncident();
  const changed = changedEvidence(incident);
  const complete =
    incident.coverage.verifiedProtectedArtifacts === incident.coverage.protectedArtifacts;
  return (
    <section className="preservationPanel" aria-labelledby="preservation-title">
      <div className="preservationScore">
        <span>Protected human content</span>
        <strong>
          {incident.coverage.verifiedProtectedArtifacts}/{incident.coverage.protectedArtifacts}
        </strong>
        <small>{complete ? 'independently matched' : 'verification pending'}</small>
      </div>
      <div className="preservationStory">
        <span className="sectionKicker">Three-way preservation proof</span>
        <h2 id="preservation-title">Registered claims can change without rewriting human prose.</h2>
        <p>
          Veritas locks a pre-mutation baseline, changes only manifest-owned anchors, and asks a
          separate verifier to compare every protected projection after repair.
        </p>
        <div className="preservationSteps">
          <div>
            <span>01</span>
            <strong>Baseline locked</strong>
            <code>{changed?.contentHash.slice(0, 14) ?? 'pending'}…</code>
          </div>
          <div>
            <span>02</span>
            <strong>Minimum write</strong>
            <code>{incident.coverage.lineagePaths} exact paths</code>
          </div>
          <div>
            <span>03</span>
            <strong>Independent compare</strong>
            <code>{complete ? 'all protected hashes match' : 'waiting behind repair gate'}</code>
          </div>
        </div>
      </div>
    </section>
  );
}

function ClaimDiffPanel({
  selectedClaim,
  onSelectClaim,
}: {
  selectedClaim: ClaimChange;
  onSelectClaim: (claimId: string) => void;
}) {
  const incident = useIncident();
  return (
    <section className="panel diffPanel proofDiffPanel" aria-labelledby="diff-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Registered claim diff</span>
          <h2 id="diff-title">What changed—and why</h2>
        </div>
        <span className={`riskTag risk-${selectedClaim.risk}`}>{selectedClaim.riskLabel}</span>
      </div>
      <div className="claimTabs" role="tablist" aria-label="Affected claims">
        {incident.claims.map((claim, index) => (
          <button
            key={claim.id}
            id={`claim-tab-${claim.id}`}
            type="button"
            role="tab"
            aria-selected={selectedClaim.id === claim.id}
            aria-controls="selected-claim-diff"
            tabIndex={selectedClaim.id === claim.id ? 0 : -1}
            data-active={selectedClaim.id === claim.id}
            onClick={() => onSelectClaim(claim.id)}
          >
            <span>{String(index + 1).padStart(2, '0')}</span>
            {claim.shortLabel}
          </button>
        ))}
      </div>
      <div
        id="selected-claim-diff"
        className="diffBody"
        role="tabpanel"
        aria-labelledby={`claim-tab-${selectedClaim.id}`}
      >
        <div className="diffLine beforeLine">
          <span className="diffSymbol" aria-hidden="true">
            −
          </span>
          <div>
            <span>Previous registered statement</span>
            <p>{selectedClaim.before}</p>
          </div>
        </div>
        <div className="diffLine afterLine">
          <span className="diffSymbol" aria-hidden="true">
            +
          </span>
          <div>
            <span>Recomputed statement</span>
            <p>{selectedClaim.after}</p>
          </div>
        </div>
        <div className="transformationRow">
          <div>
            <span>Deterministic recipe</span>
            <code>{selectedClaim.transformation}</code>
          </div>
          <div>
            <span>Evidence</span>
            <code>{selectedClaim.evidence}</code>
          </div>
          <div>
            <span>Policy</span>
            <strong>{selectedClaim.policy}</strong>
          </div>
        </div>
      </div>
    </section>
  );
}

function CertifiedReferencePanel() {
  const incident = useIncident();
  if (incident.certificate) return null;
  return (
    <section className="certifiedReference" aria-labelledby="certified-reference-title">
      <div>
        <span className="sectionKicker">Completed-state reference · offline evidence</span>
        <h2 id="certified-reference-title">See what unlocks after every gate clears.</h2>
        <p>
          This clearly labelled reference uses the deterministic judge fixture; it does not replace
          or alter the blocked live incident above.
        </p>
      </div>
      <div className="referenceCertificate">
        <span className="verifiedBadge">
          <span aria-hidden="true">✓</span> Verified reference
        </span>
        <strong>
          {demoIncident.coverage.verifiedTargets}/{demoIncident.coverage.targets}
        </strong>
        <span>targets independently re-read</span>
        <dl>
          <div>
            <dt>Checks</dt>
            <dd>{demoIncident.checks.length}</dd>
          </div>
          <div>
            <dt>Protected</dt>
            <dd>
              {demoIncident.coverage.verifiedProtectedArtifacts}/
              {demoIncident.coverage.protectedArtifacts}
            </dd>
          </div>
          <div>
            <dt>Certificate</dt>
            <dd>{demoIncident.certificate?.shortId}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function ArchitectureView() {
  return (
    <>
      <ViewHeader
        kicker="Production architecture"
        title="The model reasons inside a narrow authority envelope."
        description="Deterministic services own lineage, policy, credentials, native writes, recovery, and certification. The diagram below makes every trust boundary visible."
      />
      <section className="architectureCanvas" aria-label="Veritas production architecture">
        <div className="architectureBoundary workspaceBoundary">
          <span>Google Workspace</span>
          <div>
            <strong>Sheets + Drive</strong>
            <small>registered evidence events</small>
          </div>
          <div>
            <strong>Gmail</strong>
            <small>private customer threads</small>
          </div>
        </div>
        <span className="architectureArrow" aria-hidden="true">
          ↓ authenticated push
        </span>
        <div className="architectureRow">
          <article>
            <span>01</span>
            <strong>Event ingress</strong>
            <small>OIDC, deduplication, bounded payloads</small>
          </article>
          <i aria-hidden="true">→</i>
          <article>
            <span>02</span>
            <strong>Cloud Tasks</strong>
            <small>durable commands and retry identity</small>
          </article>
          <i aria-hidden="true">→</i>
          <article>
            <span>03</span>
            <strong>Private worker</strong>
            <small>leases, idempotency, dead letters</small>
          </article>
        </div>
        <div className="architectureCore">
          <article>
            <span>Deterministic</span>
            <strong>Claim Manifest graph</strong>
            <small>exact registered scope only</small>
          </article>
          <article className="geminiNode">
            <span>Gemini 3.5 Flash</span>
            <strong>Safety review</strong>
            <small>proceed or escalate—no tool authority</small>
          </article>
          <article>
            <span>Deterministic</span>
            <strong>Policy + repair planner</strong>
            <small>automatic, approval, draft-only</small>
          </article>
        </div>
        <span className="architectureArrow" aria-hidden="true">
          ↓ native preconditioned writes
        </span>
        <div className="architectureBoundary workspaceBoundary outputBoundary">
          <span>Owned outputs</span>
          <div>
            <strong>Docs + Slides</strong>
            <small>anchor-scoped edits</small>
          </div>
          <div>
            <strong>Gmail + Tasks</strong>
            <small>correction drafts and ETag updates</small>
          </div>
        </div>
        <div className="architectureTrustRow">
          <article>
            <strong>Cloud SQL</strong>
            <small>checksummed operational state</small>
          </article>
          <article>
            <strong>Cloud Storage + KMS</strong>
            <small>immutable snapshots and credential custody</small>
          </article>
          <article>
            <strong>Independent verifier</strong>
            <small>read-only reconstruction and certificate</small>
          </article>
        </div>
      </section>
      <PacketContractPanel />
    </>
  );
}

function PacketContractPanel() {
  const incident = useIncident();
  return (
    <section className="packetContractPanel" aria-labelledby="packet-contract-title">
      <div className="packetContractHeading">
        <div>
          <span className="sectionKicker">Reusable packet runtime</span>
          <h2 id="packet-contract-title">The Q3 scenario is input—not application code.</h2>
        </div>
        <span className="contractProofBadge">
          <i aria-hidden="true" /> Blueprint API proven live
        </span>
      </div>
      <p>
        Veritas accepts a versioned packet blueprint, materializes its native Workspace artifacts,
        and commits the resulting source-to-claim-to-target graph as a checksummed Claim Manifest.
        The same runtime executes the contract supplied by each packet.
      </p>

      <div className="packetContractFlow">
        <article>
          <span>01 · Sources</span>
          <strong>Anchored evidence</strong>
          <small>Google Sheets ranges and Google Docs anchors with native versions</small>
        </article>
        <i aria-hidden="true">→</i>
        <article>
          <span>02 · Claims</span>
          <strong>Typed transformations</strong>
          <small>Identity, comparison, threshold, recommendation, risk and freshness</small>
        </article>
        <i aria-hidden="true">→</i>
        <article>
          <span>03 · Targets</span>
          <strong>Native Workspace adapters</strong>
          <small>Docs, Slides, Gmail drafts and Google Tasks with exact ownership</small>
        </article>
      </div>

      <div className="packetContractProof">
        <code>POST /api/v1/packets</code>
        <dl>
          <div>
            <dt>Packet identity</dt>
            <dd>Caller supplied</dd>
          </div>
          <div>
            <dt>Current proof</dt>
            <dd>{incident.packetId}</dd>
          </div>
          <div>
            <dt>Registered graph</dt>
            <dd>
              {incident.coverage.sources} sources · {incident.coverage.claims} claims ·{' '}
              {incident.coverage.targets} targets
            </dd>
          </div>
          <div>
            <dt>Idempotency</dt>
            <dd>Input digest bound</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function taskTitleFromClaim(statement?: string, artifactId?: string): string {
  const fallback = artifactId
    ?.replace(/^artifact-/, '')
    .replace(/-task$/, '')
    .replaceAll('-', ' ');
  const withoutPunctuation = statement?.trim().replace(/[.!?]+$/, '') ?? '';
  const concise = withoutPunctuation
    .replace(/^the company should\s+/i, '')
    .replace(/^we should\s+/i, '')
    .replace(/^please\s+/i, '')
    .trim();
  const value = concise || fallback || 'registered task';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function displayEmailSubject(subjectLine: string): string {
  const withoutLegacyRoute = subjectLine.replace(/^\[VX-[A-F0-9]{12}\]\s*/i, '').trim();
  return withoutLegacyRoute || 'Customer email';
}

function EmailTaskAutomation({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const incident = useIncident();
  const [opened, setOpened] = useState(defaultOpen);
  const [setup, setSetup] = useState<EmailTaskSetup | null>(null);
  const [events, setEvents] = useState<ReadonlyArray<EmailTaskEvent>>([]);
  const [selectedRoute, setSelectedRoute] = useState('');
  const [authorizedSender, setAuthorizedSender] = useState('');
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [reviewingEvent, setReviewingEvent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (incident.source !== 'live' || !opened) return;
    let disposed = false;
    let refreshing = false;
    setLoading(true);
    const load = async () => {
      if (disposed || refreshing) return;
      refreshing = true;
      try {
        const packet = encodeURIComponent(incident.packetId);
        const [setupResponse, eventResponse] = await Promise.all([
          fetch(`/api/v1/email-task-workflows/setup?packetId=${packet}`, {
            credentials: 'include',
            headers: { Accept: 'application/json' },
          }),
          fetch(`/api/v1/email-task-events?packetId=${packet}`, {
            credentials: 'include',
            headers: { Accept: 'application/json' },
          }),
        ]);
        if (!setupResponse.ok) throw new Error(await safeApiError(setupResponse));
        if (!eventResponse.ok) throw new Error(await safeApiError(eventResponse));
        const nextSetup = (await setupResponse.json()) as EmailTaskSetup;
        const nextEvents = (await eventResponse.json()) as ReadonlyArray<EmailTaskEvent>;
        if (!disposed) {
          setSetup(nextSetup);
          setEvents(nextEvents);
          setSelectedRoute((value) =>
            value || nextSetup.routes.length === 0
              ? value
              : `${nextSetup.routes[0].claimId}:${nextSetup.routes[0].artifactId}`,
          );
          setError(null);
          setLoading(false);
        }
      } catch (loadError: unknown) {
        if (!disposed) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : 'Customer email automation could not be loaded.',
          );
          setLoading(false);
        }
      } finally {
        refreshing = false;
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [incident.packetId, incident.source, opened]);

  if (incident.source !== 'live') return null;

  const activeWorkflow = setup?.workflows.find(
    (workflow) => workflow.packetId === incident.packetId && workflow.status === 'active',
  );
  const activeRoute = activeWorkflow
    ? setup?.routes.find(
        (item) =>
          item.claimId === activeWorkflow.claimId && item.artifactId === activeWorkflow.artifactId,
      )
    : undefined;
  const route = setup?.routes.find(
    (item) => `${item.claimId}:${item.artifactId}` === selectedRoute,
  );
  const boundTaskTitle = taskTitleFromClaim(
    activeRoute?.claimStatement,
    activeWorkflow?.artifactId,
  );
  const activeThread = activeWorkflow
    ? setup?.threads.find((thread) => thread.workflowId === activeWorkflow.workflowId)
    : undefined;
  const pendingUnmatched =
    setup?.unmatchedRequests.filter((request) => request.status === 'pending') ?? [];
  const conversationSubject = activeThread?.subjectLine ?? `${boundTaskTitle} — customer update`;
  const gmailThreadUrl = activeWorkflow
    ? `https://mail.google.com/mail/u/?authuser=${encodeURIComponent(activeWorkflow.mailboxEmail)}#search/${encodeURIComponent(`subject:"${conversationSubject}"`)}`
    : null;

  async function registerWorkflow() {
    if (!setup || !route || !authorizedSender.trim()) return;
    setWorking(true);
    setError(null);
    try {
      const response = await fetch('/api/v1/email-task-workflows', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          packetId: setup.packetId,
          claimId: route.claimId,
          artifactId: route.artifactId,
          authorizedSender: authorizedSender.trim(),
        }),
      });
      if (!response.ok) throw new Error(await safeApiError(response));
      const result = (await response.json()) as {
        workflow: EmailTaskWorkflow;
      };
      setSetup({
        ...setup,
        workflows: [
          result.workflow,
          ...setup.workflows.filter(
            (workflow) => workflow.workflowId !== result.workflow.workflowId,
          ),
        ],
      });
      setAuthorizedSender('');
    } catch (registerError: unknown) {
      setError(
        registerError instanceof Error
          ? registerError.message
          : 'The customer and task could not be registered.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function startConversation() {
    if (!setup || !activeWorkflow) return;
    setWorking(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/email-task-workflows/${encodeURIComponent(activeWorkflow.workflowId)}/conversation`,
        { method: 'POST', credentials: 'include', headers: { Accept: 'application/json' } },
      );
      if (!response.ok) throw new Error(await safeApiError(response));
      const thread = (await response.json()) as EmailTaskThreadBinding;
      setSetup({
        ...setup,
        threads: [thread, ...setup.threads.filter((item) => item.bindingId !== thread.bindingId)],
      });
    } catch (conversationError: unknown) {
      setError(
        conversationError instanceof Error
          ? conversationError.message
          : 'The customer conversation could not be started.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function bindUnmatched(request: EmailTaskUnmatchedRequest) {
    if (!setup || !activeWorkflow) return;
    setWorking(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/email-task-unmatched/${encodeURIComponent(request.requestId)}/bind`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ workflowId: activeWorkflow.workflowId }),
        },
      );
      if (!response.ok) throw new Error(await safeApiError(response));
      const thread = (await response.json()) as EmailTaskThreadBinding;
      setSetup({
        ...setup,
        threads: [thread, ...setup.threads.filter((item) => item.bindingId !== thread.bindingId)],
        unmatchedRequests: setup.unmatchedRequests.map((item) =>
          item.requestId === request.requestId
            ? { ...item, status: 'bound', boundWorkflowId: activeWorkflow.workflowId }
            : item,
        ),
      });
    } catch (bindError: unknown) {
      setError(
        bindError instanceof Error
          ? bindError.message
          : 'The customer conversation could not be connected.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function disableWorkflow() {
    if (!setup || !activeWorkflow) return;
    setWorking(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/email-task-workflows/${encodeURIComponent(activeWorkflow.workflowId)}`,
        { method: 'DELETE', credentials: 'include', headers: { Accept: 'application/json' } },
      );
      if (!response.ok) throw new Error(await safeApiError(response));
      const paused = (await response.json()) as EmailTaskWorkflow;
      setSetup({
        ...setup,
        workflows: setup.workflows.map((workflow) =>
          workflow.workflowId === paused.workflowId ? paused : workflow,
        ),
      });
    } catch (disableError: unknown) {
      setError(
        disableError instanceof Error
          ? disableError.message
          : 'The customer conversation automation could not be disabled.',
      );
    } finally {
      setWorking(false);
    }
  }

  async function reviewEmailEvent(event: EmailTaskEvent, decision: 'approve' | 'reject') {
    setReviewingEvent(event.eventId);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/email-task-events/${encodeURIComponent(event.eventId)}/review`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            requestId: crypto.randomUUID(),
            decision,
            reason:
              decision === 'approve'
                ? 'Approved by the authenticated operator after reviewing the customer request and current task.'
                : 'Rejected by the authenticated operator after reviewing the customer request and current task.',
          }),
        },
      );
      if (!response.ok) throw new Error(await safeApiError(response));
      const result = (await response.json()) as { event: EmailTaskEvent };
      setEvents((current) =>
        current.map((item) => (item.eventId === result.event.eventId ? result.event : item)),
      );
    } catch (reviewError: unknown) {
      setError(
        reviewError instanceof Error
          ? reviewError.message
          : 'The escalated customer request could not be reviewed.',
      );
    } finally {
      setReviewingEvent(null);
    }
  }

  return (
    <section className="panel emailAutomationPanel" aria-labelledby="email-automation-title">
      <div className="emailAutomationIntro">
        <span className="sectionKicker">Customer signal → owned action</span>
        <h2 id="email-automation-title">One normal email. One exact task. Full proof.</h2>
        <p>
          Veritas privately binds a normal Gmail conversation to the exact Google Task already
          registered in the Claim Manifest. Customers only press Reply—there are no codes to copy.
        </p>
        <ol className="emailFlow" aria-label="Email automation flow">
          <li>
            <span>01</span> Company starts a normal thread
          </li>
          <li>
            <span>02</span> Customer simply replies
          </li>
          <li>
            <span>03</span> The owned task updates
          </li>
        </ol>
      </div>

      {!opened ? (
        <div className="emailCallToAction">
          <p>
            Connect one real customer and one registered Google Task. Veritas creates a normal
            company email, remembers its Gmail thread privately, and proves every later reply.
          </p>
          <button className="primaryButton" type="button" onClick={() => setOpened(true)}>
            Set up customer email
          </button>
        </div>
      ) : loading ? (
        <p className="emailEmpty" role="status">
          Loading the registered task route…
        </p>
      ) : activeWorkflow ? (
        <div className="emailAutomationBody">
          <section className="automationRoute" aria-label="Active email route">
            <div>
              <span>Authorized customer</span>
              <strong>{activeWorkflow.authorizedSender}</strong>
            </div>
            <i aria-hidden="true">→</i>
            <div>
              <span>Company inbox</span>
              <strong>{activeWorkflow.mailboxEmail}</strong>
            </div>
            <i aria-hidden="true">→</i>
            <div>
              <span>{activeThread ? 'Thread-bound task' : 'Manifest-bound task'}</span>
              <strong>{boundTaskTitle}</strong>
              <small>Google Tasks · {activeWorkflow.artifactId}</small>
            </div>
          </section>

          <div className="emailDemoCard">
            {activeThread ? (
              <>
                <div className="emailField">
                  <span>Conversation</span>
                  <strong>{conversationSubject}</strong>
                </div>
                <div className="emailField">
                  <span>Started by</span>
                  <strong>{activeWorkflow.mailboxEmail}</strong>
                </div>
                <div className="emailField">
                  <span>Customer</span>
                  <strong>{activeWorkflow.authorizedSender}</strong>
                </div>
                <div className="emailField emailBodyField">
                  <span>What the customer does</span>
                  <p>
                    Open this ordinary email and press Reply. Veritas recognizes the private Gmail
                    thread, verifies the sender, and updates only “{boundTaskTitle}”.
                  </p>
                </div>
                <p className="emailSenderGuard successGuard">
                  No routing code is visible or required. New, unrelated emails never mutate a task
                  automatically; they wait in Unmatched requests.
                </p>
                <div className="emailDemoActions">
                  <a
                    className="primaryButton"
                    href={gmailThreadUrl ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open company conversation ↗
                  </a>
                  <a
                    className="secondaryButton"
                    href="https://tasks.google.com/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Google Tasks ↗
                  </a>
                  <button
                    className="dangerButton"
                    type="button"
                    disabled={working}
                    onClick={() => void disableWorkflow()}
                  >
                    {working ? 'Disabling…' : 'Disable automation'}
                  </button>
                </div>
              </>
            ) : (
              <div className="conversationStart">
                <span className="sectionKicker">Private thread setup</span>
                <h3>Start one normal customer conversation</h3>
                <p>
                  Veritas will send a regular email from {activeWorkflow.mailboxEmail} to{' '}
                  {activeWorkflow.authorizedSender}. Its Gmail thread—not its subject text—will own
                  the connection to “{boundTaskTitle}”.
                </p>
                <button
                  className="primaryButton"
                  type="button"
                  disabled={working}
                  onClick={() => void startConversation()}
                >
                  {working ? 'Starting conversation…' : 'Send opening email & bind thread'}
                </button>
              </div>
            )}
          </div>

          <div className="emailReceiptHeader unmatchedHeader">
            <div>
              <span className="sectionKicker">Safe ambiguity queue</span>
              <h3>Unmatched requests</h3>
            </div>
            <span className="watchBadge neutralBadge">
              {pendingUnmatched.length} awaiting connection
            </span>
          </div>
          {pendingUnmatched.length === 0 ? (
            <p className="emailEmpty">
              No authorized customer has started an unrelated conversation.
            </p>
          ) : (
            <div className="emailEventList unmatchedList">
              {pendingUnmatched.map((request) => (
                <article key={request.requestId}>
                  <span className="emailEventStatus status-escalated">needs routing</span>
                  <div>
                    <strong>{request.subjectLine}</strong>
                    <span>
                      {fullUtc(request.receivedAt)} · from {request.sender}
                    </span>
                    <p>
                      Veritas recognized an authorized customer but refused to guess which task the
                      new Gmail thread owns.
                    </p>
                  </div>
                  <dl>
                    <div>
                      <dt>Body proof</dt>
                      <dd>{request.bodyHash.slice(0, 12)}…</dd>
                    </div>
                    <div>
                      <dt>Receipt</dt>
                      <dd>{request.receiptChecksum.slice(0, 12)}…</dd>
                    </div>
                  </dl>
                  {request.candidateWorkflowIds.includes(activeWorkflow.workflowId) && (
                    <button
                      className="secondaryButton"
                      type="button"
                      disabled={working}
                      onClick={() => void bindUnmatched(request)}
                    >
                      Connect this thread to {boundTaskTitle}
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}

          <div className="emailReceiptHeader">
            <div>
              <span className="sectionKicker">Live receipts</span>
              <h3>Email-to-task activity</h3>
            </div>
            <span className="watchBadge">
              <i aria-hidden="true" /> Inbox watch active
            </span>
          </div>
          {events.length === 0 ? (
            <p className="emailEmpty">
              No reply has been processed yet. Customer replies appear here automatically; this list
              refreshes every 3 seconds.
            </p>
          ) : (
            <div className="emailEventList">
              {events.map((event) => (
                <article key={event.eventId}>
                  <span className={`emailEventStatus status-${event.status}`}>{event.status}</span>
                  <div>
                    <strong>{event.proposedTitle ?? displayEmailSubject(event.subjectLine)}</strong>
                    <span>
                      {fullUtc(event.receivedAt)} · from {event.sender}
                    </span>
                    <p>{event.rationale}</p>
                    {event.status === 'escalated' && event.proposedTitle && event.proposedNote && (
                      <div className="emailProposal">
                        <span>Proposed Google Task update</span>
                        <strong>{event.proposedTitle}</strong>
                        <p>{event.proposedNote}</p>
                      </div>
                    )}
                    {event.reviewedBy && event.reviewDecision && (
                      <p className="emailReviewProof">
                        {event.reviewDecision === 'approve' ? 'Approved' : 'Rejected'} by{' '}
                        {event.reviewedBy}
                        {event.reviewedAt ? ` at ${fullUtc(event.reviewedAt)}` : ''}.
                      </p>
                    )}
                  </div>
                  <dl>
                    <div>
                      <dt>Body proof</dt>
                      <dd>{event.bodyHash.slice(0, 12)}…</dd>
                    </div>
                    <div>
                      <dt>Receipt</dt>
                      <dd>{event.receiptChecksum.slice(0, 12)}…</dd>
                    </div>
                    <div>
                      <dt>Task revision</dt>
                      <dd>{event.taskRevision ?? 'not changed'}</dd>
                    </div>
                    {event.reviewReceiptChecksum && (
                      <div>
                        <dt>Review receipt</dt>
                        <dd>{event.reviewReceiptChecksum.slice(0, 12)}…</dd>
                      </div>
                    )}
                  </dl>
                  {event.status === 'escalated' && (
                    <fieldset className="emailReviewActions">
                      <legend className="srOnly">Human authority decision</legend>
                      <button
                        className="primaryButton"
                        type="button"
                        disabled={reviewingEvent !== null}
                        onClick={() => void reviewEmailEvent(event, 'approve')}
                      >
                        {reviewingEvent === event.eventId
                          ? 'Applying approved update…'
                          : 'Approve & update task'}
                      </button>
                      <button
                        className="dangerButton"
                        type="button"
                        disabled={reviewingEvent !== null}
                        onClick={() => void reviewEmailEvent(event, 'reject')}
                      >
                        Reject request
                      </button>
                    </fieldset>
                  )}
                </article>
              ))}
            </div>
          )}
        </div>
      ) : (
        <form
          className="emailSetupForm"
          onSubmit={(event) => {
            event.preventDefault();
            void registerWorkflow();
          }}
        >
          <div className="emailSetupGrid">
            <label>
              <span>Company inbox being watched</span>
              <input value={setup?.mailboxEmail ?? 'Connected Google account'} readOnly />
            </label>
            <label>
              <span>Customer allowed to trigger updates</span>
              <input
                type="email"
                required
                autoComplete="email"
                placeholder="customer@company.com"
                value={authorizedSender}
                onChange={(event) => setAuthorizedSender(event.target.value)}
              />
            </label>
            <label>
              <span>Registered claim → Google Task</span>
              <select
                required
                value={selectedRoute}
                onChange={(event) => setSelectedRoute(event.target.value)}
                disabled={!setup || setup.routes.length === 0}
              >
                {setup?.routes.map((item) => (
                  <option
                    key={`${item.claimId}:${item.artifactId}`}
                    value={`${item.claimId}:${item.artifactId}`}
                  >
                    {item.claimStatement} → {item.artifactId.replaceAll('-', ' ')}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="emailSetupFooter">
            <p>
              Veritas will create a normal company-to-customer conversation next. Only replies in
              its private Gmail thread can reach this registered task; ambiguity stops for review.
            </p>
            <button
              className="primaryButton"
              type="submit"
              disabled={working || !route || !authorizedSender.trim()}
            >
              {working ? 'Registering customer…' : 'Register customer & task'}
            </button>
          </div>
        </form>
      )}
      {setup && setup.routes.length === 0 && (
        <p className="actionNotice">
          This packet has no Claim Manifest edge to a Google Task, so Veritas correctly refuses to
          invent one.
        </p>
      )}
      {error && (
        <p className="actionError" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function ApprovalQueue({ onIncidentChange }: { onIncidentChange: (incident: Incident) => void }) {
  const incident = useIncident();
  const pending = incident.approvals.filter((approval) => approval.status === 'pending');
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestIds = useRef(new Map<string, string>());
  if (pending.length === 0) return null;
  const authorityReady = incident.status === 'awaiting_approval';
  const runMissing = incident.source === 'live' && !incident.runId;

  async function decide(approval: IncidentApproval, decision: 'approve' | 'reject') {
    if (incident.source !== 'live') return;
    setWorking(approval.approvalId);
    setError(null);
    try {
      const requestKey = `${approval.approvalId}:${decision}`;
      const requestId = requestIds.current.get(requestKey) ?? crypto.randomUUID();
      requestIds.current.set(requestKey, requestId);
      if (!approval.runId) throw new Error('approval_run_missing');
      const response = await fetch(
        `/api/v1/command-center/incidents/${encodeURIComponent(approval.planId)}/runs/${encodeURIComponent(approval.runId)}/approvals/${encodeURIComponent(approval.approvalId)}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            requestId,
            decision,
            reason:
              decision === 'approve'
                ? 'Reviewed the registered impact and approved this decision-changing repair.'
                : 'Reviewed the registered impact and rejected this decision-changing repair.',
          }),
        },
      );
      if (!response.ok) throw new Error(`approval_${response.status}`);
      const refreshed = await fetch('/api/v1/command-center/incidents/latest', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!refreshed.ok) throw new Error(`refresh_${refreshed.status}`);
      const result = (await refreshed.json()) as Incident | null;
      if (!result) throw new Error('incident_missing');
      onIncidentChange(result);
      requestIds.current.delete(requestKey);
    } catch {
      try {
        const refreshed = await fetch('/api/v1/command-center/incidents/latest', {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        if (refreshed.ok) {
          const latest = (await refreshed.json()) as Incident | null;
          if (latest) onIncidentChange(latest);
        }
      } catch {
        // Preserve the idempotency key so the same decision can be retried safely.
      }
      setError(
        'Continuation paused before confirmation. Retry the same decision safely; its request receipt is preserved.',
      );
    } finally {
      setWorking(null);
    }
  }

  return (
    <section className="panel approvalPanel" aria-labelledby="approval-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Human authority boundary</span>
          <h2 id="approval-title">Decision-changing consequences need your approval</h2>
        </div>
        <span className="severity">{pending.length} pending</span>
      </div>
      <div className="approvalList">
        {pending.map((approval) => (
          <article key={approval.approvalId}>
            <div>
              <strong>{approval.claimLabel}</strong>
              <span>Automatic factual repairs are preserved; this decision step is paused.</span>
            </div>
            <div className="approvalActions">
              <button
                className="secondaryButton"
                type="button"
                disabled={working !== null || incident.source !== 'live' || !authorityReady}
                onClick={() => decide(approval, 'reject')}
              >
                Reject
              </button>
              <button
                className="replayButton"
                type="button"
                disabled={working !== null || incident.source !== 'live' || !authorityReady}
                onClick={() => decide(approval, 'approve')}
              >
                {working === approval.approvalId ? 'Applying decision…' : 'Approve & continue'}
              </button>
            </div>
          </article>
        ))}
      </div>
      {!authorityReady && (
        <p className="actionNotice" role="status">
          {runMissing
            ? 'This plan stopped before a durable repair run was created. Replay the quarantined operation to revalidate the evidence and unlock decisions safely.'
            : incident.status === 'attention'
              ? 'The automatic run stopped safely on a preserved conflict. Resolve or replay that attention item before these decisions and independent verification can unlock.'
              : 'Safe automatic work is still running. Decisions unlock only after the durable run reaches the human authority boundary.'}
        </p>
      )}
      {error && (
        <p className="actionError" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function RecoveryQueue({ onIncidentChange }: { onIncidentChange: (incident: Incident) => void }) {
  const incident = useIncident();
  const [deadLetters, setDeadLetters] = useState<ReadonlyArray<DeadLetterSummary>>([]);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const replayed = useRef(new Set<string>());
  const needsRecovery =
    incident.source === 'live' &&
    !incident.agentReview &&
    (!incident.runId || incident.status === 'repairing');

  useEffect(() => {
    if (!needsRecovery) return;
    let disposed = false;
    const refresh = async () => {
      setLoading(true);
      try {
        const response = await fetch('/api/v1/operations/dead-letters', {
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) return;
        const result = (await response.json()) as ReadonlyArray<DeadLetterSummary>;
        if (!disposed) {
          const detectedAt = new Date(incident.detectedAt).getTime();
          setDeadLetters(
            result
              .filter(
                (item) =>
                  !replayed.current.has(item.operationId) &&
                  item.packetIds.includes(incident.packetId) &&
                  new Date(item.updatedAt).getTime() >= detectedAt,
              )
              .sort(
                (left, right) =>
                  new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
              ),
          );
        }
      } catch {
        // The incident remains visible while operator evidence is temporarily unavailable.
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [incident.detectedAt, incident.packetId, needsRecovery]);

  if (!needsRecovery || (loading && deadLetters.length === 0)) return null;
  const newest = deadLetters[0];
  if (!newest && !message) return null;

  async function replay(operation: DeadLetterSummary) {
    setWorking(operation.operationId);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/v1/operations/dead-letters/${encodeURIComponent(operation.operationId)}/replay`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            requestId: crypto.randomUUID(),
            reason: 'Dependency recovered; resume the evidence-bound operation after review.',
          }),
        },
      );
      if (!response.ok) throw new Error(await safeApiError(response));
      replayed.current.add(operation.operationId);
      setDeadLetters((current) =>
        current.filter((item) => item.operationId !== operation.operationId),
      );
      setMessage('Audited replay queued. Existing receipts and completed writes remain preserved.');
      const refreshed = await fetch('/api/v1/command-center/incidents/latest', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (refreshed.ok) {
        const result = (await refreshed.json()) as Incident | null;
        if (result) onIncidentChange(result);
      }
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : 'Audited replay could not be queued.');
    } finally {
      setWorking(null);
    }
  }

  return (
    <section className="panel recoveryPanel" aria-labelledby="recovery-title">
      <div className="panelHeader">
        <div>
          <span className="sectionKicker">Durable recovery boundary</span>
          <h2 id="recovery-title">The agent stopped safely. Recovery needs an operator.</h2>
        </div>
        <span className="severity">{newest ? 'Quarantined' : 'Recovery queued'}</span>
      </div>
      {newest && (
        <article className="recoveryOperation">
          <div>
            <strong>{newest.errorCode.replaceAll('_', ' ')}</strong>
            <span>
              {newest.kind} · {newest.attempt}/{newest.maxAttempts} attempts · fingerprint{' '}
              <code>{newest.diagnosticFingerprint}</code>
            </span>
            <small>
              Original operation <code>{newest.operationId}</code> remains immutable. Replay creates
              a linked operation and revalidates source versions before any write.
            </small>
          </div>
          <button
            className="replayButton"
            type="button"
            disabled={working !== null}
            onClick={() => void replay(newest)}
          >
            {working === newest.operationId ? 'Queuing audited replay…' : 'Replay safely'}
          </button>
        </article>
      )}
      {message && (
        <p className="actionNotice" role="status">
          {message}
        </p>
      )}
    </section>
  );
}

function ConsequenceMap({ replayStage }: { replayStage: number }) {
  const incident = useIncident();
  const source = changedEvidence(incident);
  return (
    <section className="panel consequenceMap" aria-labelledby="consequence-title">
      <div className="consequenceHeader">
        <div>
          <span className="sectionKicker">Registered consequence map</span>
          <h2 id="consequence-title">The source moved. Veritas knew exactly what it owned.</h2>
          <p>
            No similarity search. No guessed relationships. Every path came from the Claim Manifest.
          </p>
        </div>
        <span className="manifestBadge">
          <i aria-hidden="true" /> Manifest-bound
        </span>
      </div>

      <div className="consequenceFlow">
        <div className="flowColumn sourceFlowColumn" data-visible={replayStage >= 1}>
          <span className="flowLabel">01 · evidence</span>
          <article className="flowSource">
            <span className="flowAppIcon">S</span>
            <div>
              <small>
                {source?.kind ?? 'Evidence'} · {source?.anchor ?? 'registered anchor'}
              </small>
              <strong>{source?.label ?? 'Changed evidence'}</strong>
              <span>semantic change accepted</span>
            </div>
          </article>
        </div>

        <div className="flowBridge" data-visible={replayStage >= 2} aria-hidden="true">
          <span>semantic delta</span>
          <i />
        </div>

        <div className="flowColumn" data-visible={replayStage >= 2}>
          <span className="flowLabel">02 · {incident.claims.length} affected claims</span>
          <div className="claimFlowGrid">
            {incident.claims.map((claim, index) => (
              <article className="flowClaim" key={claim.id}>
                <span>0{index + 1}</span>
                <div>
                  <strong>{claim.shortLabel}</strong>
                  <small>{claim.targetCount} registered targets</small>
                </div>
              </article>
            ))}
          </div>
        </div>

        <div className="flowBridge" data-visible={replayStage >= 3} aria-hidden="true">
          <span>exact registered paths</span>
          <i />
        </div>

        <div className="flowColumn" data-visible={replayStage >= 3}>
          <span className="flowLabel">03 · {incident.artifacts.length} repaired artifacts</span>
          <div className="artifactFlowGrid">
            {incident.artifacts.map((artifact) => (
              <article className="flowArtifact" key={artifact.id}>
                <span
                  className={`surfaceIcon surface-${artifact.code.toLowerCase()}`}
                  aria-hidden="true"
                >
                  {artifact.code}
                </span>
                <div>
                  <strong>{artifact.name}</strong>
                  <small>
                    {artifact.result} · {artifact.guardrail}
                  </small>
                </div>
                <span className="flowCheck" aria-hidden="true">
                  ✓
                </span>
              </article>
            ))}
          </div>
        </div>
      </div>

      <div className="consequenceGuardrails">
        <span>
          <i aria-hidden="true">✓</i> 0 inferred paths
        </span>
        <span>
          <i aria-hidden="true">✓</i> 0 human edits lost
        </span>
        <span>
          <i aria-hidden="true">✓</i> Sent email left immutable
        </span>
        <span>
          <i aria-hidden="true">✓</i> {incident.coverage.verifiedTargets}/
          {incident.coverage.targets} targets independently verified
        </span>
      </div>
    </section>
  );
}

function Metric({
  value,
  label,
  detail,
  accent = false,
}: {
  value: string;
  label: string;
  detail: string;
  accent?: boolean;
}) {
  return (
    <article className="metric" data-accent={accent}>
      <strong>{value}</strong>
      <div>
        <span>{label}</span>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function RunProgressRibbon({
  activeStage,
  isStreaming,
}: {
  activeStage: number;
  isStreaming: boolean;
}) {
  const incident = useIncident();
  const visibleEvents = incident.timeline.slice(0, activeStage);
  const visibleLabels = new Set(visibleEvents.map((event) => event.label.toLowerCase()));
  const detected = visibleLabels.has('detected');
  const traced = visibleLabels.has('traced');
  const reviewed = traced && incident.agentReview !== null;
  const repaired = visibleLabels.has('repaired');
  const verified = visibleLabels.has('verified') || incident.checks.length > 0;
  const certified = visibleLabels.has('certified') || incident.certificate !== null;
  const progress = [
    { label: 'Detected', detail: 'Source delta', complete: detected },
    { label: 'Snapshot sealed', detail: 'Immutable evidence', complete: detected },
    {
      label: 'Claims traced',
      detail: `${incident.coverage.affectedClaims} affected`,
      complete: traced,
    },
    {
      label: 'Gemini reviewed',
      detail: incident.agentReview?.disposition ?? 'bounded decision',
      complete: reviewed,
    },
    {
      label: 'Workspace repaired',
      detail: `${incident.artifacts.length} artifacts`,
      complete: repaired,
    },
    {
      label: 'Independently verified',
      detail: `${incident.coverage.verifiedTargets}/${incident.coverage.targets} targets`,
      complete: verified,
    },
    {
      label: 'Certificate issued',
      detail: incident.certificate?.shortId ?? 'scoped proof',
      complete: certified,
    },
  ];
  const activeIndex = progress.findIndex((step) => !step.complete);
  return (
    <section className="runProgress" aria-labelledby="run-progress-title">
      <div className="runProgressTopline">
        <div>
          <span className="sectionKicker">One autonomous transaction</span>
          <h2 id="run-progress-title">Source truth → repaired consequences → proof</h2>
        </div>
        <span className="runProgressState" data-streaming={isStreaming}>
          <i aria-hidden="true" />
          {certified ? 'Transaction sealed' : isStreaming ? 'Advancing live' : 'Persisted state'}
        </span>
      </div>
      <ol>
        {progress.map((step, index) => {
          const active = !step.complete && index === activeIndex;
          return (
            <li key={step.label} data-complete={step.complete} data-active={active}>
              <span aria-hidden="true">
                {step.complete ? '✓' : String(index + 1).padStart(2, '0')}
              </span>
              <div>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function GeminiDecisionReceipt({ visible }: { visible: boolean }) {
  const incident = useIncident();
  const review = visible ? incident.agentReview : null;
  const source = changedEvidence(incident);
  const sourceValues = sourceTransitionValues(incident);
  return (
    <section
      className="geminiDecision"
      data-pending={!review}
      aria-labelledby="gemini-decision-title"
    >
      <div className="geminiDecisionIntro">
        <div className="geminiDecisionMark" aria-hidden="true">
          G
        </div>
        <div>
          <span className="sectionKicker">Material agent decision</span>
          <h2 id="gemini-decision-title">Gemini interprets the risk. Policy owns authority.</h2>
          <p>
            The model reviews the semantic change and exact registered claim set. It may proceed or
            stop the run, but it cannot invent scope, approve decisions, write outside the manifest,
            or certify itself.
          </p>
        </div>
      </div>

      {review ? (
        <div className="geminiDecisionBody">
          <div className="geminiDecisionInput">
            <span>Structured input</span>
            <dl>
              <div>
                <dt>Evidence delta</dt>
                <dd>
                  <code>{source?.anchor ?? 'registered anchor'}</code>
                  <strong>
                    {sourceValues.before} → {sourceValues.after}
                  </strong>
                </dd>
              </div>
              <div>
                <dt>Exact scope</dt>
                <dd>
                  <strong>{incident.coverage.affectedClaims} affected claims</strong>
                  <small>{incident.coverage.lineagePaths} registered paths · 0 inferred</small>
                </dd>
              </div>
              <div>
                <dt>Decision risks</dt>
                <dd className="geminiClaimScope">
                  {incident.claims.map((claim) => (
                    <span key={claim.id} data-risk={claim.risk}>
                      {claim.shortLabel}
                    </span>
                  ))}
                </dd>
              </div>
            </dl>
          </div>

          <div className="geminiDecisionOutput">
            <div className="geminiDecisionTopline">
              <span>{review.model}</span>
              <strong data-disposition={review.disposition}>{review.disposition}</strong>
            </div>
            <blockquote>{review.rationale}</blockquote>
            <div className="geminiRiskFlags">
              <span>Risk flags</span>
              {review.riskFlags.length > 0 ? (
                review.riskFlags.map((flag) => <strong key={flag}>{flag}</strong>)
              ) : (
                <strong>No additional model risk flags</strong>
              )}
            </div>
            <code className="geminiReceiptChecksum">receipt · {review.receipt}</code>
          </div>
        </div>
      ) : (
        <div className="geminiDecisionPending">
          <span className="terminalPrompt" aria-hidden="true">
            ›
          </span>
          Waiting for the persisted Gemini review receipt…
        </div>
      )}

      <ul className="geminiAuthority" aria-label="Gemini authority limits">
        <li>
          <span>Cannot</span>
          <strong>Expand registered scope</strong>
        </li>
        <li>
          <span>Cannot</span>
          <strong>Approve decision changes</strong>
        </li>
        <li>
          <span>Cannot</span>
          <strong>Issue the certificate</strong>
        </li>
      </ul>
    </section>
  );
}

function Timeline({ activeStage, isStreaming }: { activeStage: number; isStreaming: boolean }) {
  const incident = useIncident();
  const visibleEvents = incident.timeline.slice(0, activeStage);
  const visibleLabels = new Set(visibleEvents.map((event) => event.label.toLowerCase()));
  const pendingApprovals = incident.approvals.filter(
    (approval) => approval.status === 'pending',
  ).length;
  const sourceReady = visibleLabels.has('detected');
  const lineageReady = visibleLabels.has('traced');
  const requiresAttention = incident.status === 'attention';
  const repairReady = visibleLabels.has('repaired') && !requiresAttention;
  const verifierReady = visibleLabels.has('verified') || incident.checks.length > 0;
  const streamState = isStreaming
    ? 'Streaming signed receipts'
    : requiresAttention
      ? 'Attention · run conflict'
      : pendingApprovals > 0
        ? `Paused · ${pendingApprovals} approval${pendingApprovals === 1 ? '' : 's'}`
        : incident.status === 'verified'
          ? 'Sealed · certificate issued'
          : 'Watching Workspace';
  return (
    <section className="executionObservatory" aria-labelledby="timeline-title">
      <header className="executionHeader">
        <div>
          <span className="sectionKicker">Live execution observatory</span>
          <h2 id="timeline-title">Watch the agent move through the causal graph.</h2>
          <p>Persisted backend receipts appear here automatically—no page reload required.</p>
        </div>
        <span className="executionConnection" data-streaming={isStreaming}>
          <i aria-hidden="true" /> {streamState}
        </span>
      </header>

      <div className="executionBody">
        <div className="executionTerminal" role="log" aria-label="Live signed execution receipts">
          <div className="terminalTopline">
            <span>VERITAS / RUN {incident.id.slice(-8).toUpperCase()}</span>
            <span>3S LIVE POLL</span>
          </div>
          <ol aria-live="polite" aria-relevant="additions">
            {visibleEvents.map((event, index) => (
              <li
                key={`${event.label}-${event.occurredAt}-${event.receipt}`}
                data-newest={index === visibleEvents.length - 1}
              >
                <time dateTime={event.occurredAt}>{event.time}</time>
                <strong>{event.label.toUpperCase()}</strong>
                <span>{event.detail}</span>
                <code title={`Proof receipt ${event.receipt}`}>{event.receipt.slice(0, 10)}</code>
              </li>
            ))}
            {visibleEvents.length === 0 && (
              <li className="terminalWaiting">
                <span className="terminalPrompt" aria-hidden="true">
                  ›
                </span>
                <span>Reading the first persisted receipt…</span>
              </li>
            )}
          </ol>
          <div className="terminalGate" data-status={incident.status}>
            <span className="terminalPrompt" aria-hidden="true">
              ›
            </span>
            <strong>
              {requiresAttention
                ? 'OPERATOR ATTENTION'
                : pendingApprovals > 0
                  ? 'HUMAN AUTHORITY BOUNDARY'
                  : incident.status === 'verified'
                    ? 'INDEPENDENT VERIFIER'
                    : 'EVENT WATCH'}
            </strong>
            <span>
              {requiresAttention
                ? `A repair conflict stopped the run safely. Resolve or replay it before ${pendingApprovals} approval${pendingApprovals === 1 ? '' : 's'} and verification.`
                : pendingApprovals > 0
                  ? `${pendingApprovals} decision${pendingApprovals === 1 ? '' : 's'} waiting; safe automatic work remains preserved.`
                  : incident.status === 'verified'
                    ? `${incident.checks.length} checks persisted; ${incident.certificate?.shortId ?? 'certificate'} sealed.`
                    : 'Waiting for the next registered Workspace change.'}
            </span>
          </div>
          <small>Append-only evidence · receipt IDs shown at right · no simulated log lines</small>
        </div>

        <div
          className="executionGraph"
          role="img"
          aria-label={`Live causal graph: source ${sourceReady ? 'accepted' : 'waiting'}, claims ${lineageReady ? 'traced' : 'waiting'}, repairs ${repairReady ? 'complete' : requiresAttention ? 'blocked by conflict' : pendingApprovals > 0 ? 'waiting for approval' : 'pending'}, verifier ${verifierReady ? 'complete' : 'pending'}`}
        >
          <div className="executionGraphLabel">
            <span>Causal graph state</span>
            <code>{incident.packetId}</code>
          </div>
          <div className="executionGraphPath" data-streaming={isStreaming}>
            <article data-state={sourceReady ? 'complete' : 'waiting'}>
              <i aria-hidden="true">01</i>
              <div>
                <span>Evidence</span>
                <strong>{sourceReady ? 'Delta accepted' : 'Watching source'}</strong>
                <small>{changedEvidence(incident)?.anchor ?? 'registered anchor'}</small>
              </div>
            </article>
            <span className="executionEdge" data-active={lineageReady} aria-hidden="true" />
            <article data-state={lineageReady ? 'complete' : 'waiting'}>
              <i aria-hidden="true">02</i>
              <div>
                <span>Claim graph</span>
                <strong>
                  {lineageReady
                    ? `${incident.coverage.affectedClaims} claims resolved`
                    : 'Awaiting trace'}
                </strong>
                <small>{incident.coverage.lineagePaths} manifest paths</small>
              </div>
            </article>
            <span
              className="executionEdge"
              data-active={repairReady || pendingApprovals > 0 || requiresAttention}
              aria-hidden="true"
            />
            <article
              data-state={
                repairReady || pendingApprovals > 0 || requiresAttention
                  ? repairReady
                    ? 'complete'
                    : 'active'
                  : 'waiting'
              }
            >
              <i aria-hidden="true">03</i>
              <div>
                <span>Repair boundary</span>
                <strong>
                  {repairReady
                    ? `${incident.artifacts.length} artifacts repaired`
                    : requiresAttention
                      ? 'Run conflict requires review'
                      : pendingApprovals > 0
                        ? `${pendingApprovals} approvals required`
                        : 'Plan is materializing'}
                </strong>
                <small>
                  {requiresAttention
                    ? `${incident.artifacts.filter((artifact) => artifact.result.includes('attention')).length} artifact conflict persisted`
                    : 'registered targets only'}
                </small>
              </div>
            </article>
            <span className="executionEdge" data-active={verifierReady} aria-hidden="true" />
            <article data-state={verifierReady ? 'complete' : 'waiting'}>
              <i aria-hidden="true">04</i>
              <div>
                <span>Independent verifier</span>
                <strong>
                  {verifierReady
                    ? `${incident.coverage.verifiedTargets}/${incident.coverage.targets} re-read`
                    : 'Waiting for terminal run'}
                </strong>
                <small>{incident.checks.length} persisted checks</small>
              </div>
            </article>
          </div>
        </div>
      </div>

      <ol className="timeline" aria-label="Signed execution stages">
        {incident.timeline.map((event, index) => {
          const completed = index < activeStage;
          const active = index === activeStage;
          return (
            <li key={event.label} data-complete={completed} data-active={active}>
              <span className="timelineMarker" aria-hidden="true">
                {completed ? '✓' : index + 1}
              </span>
              <div>
                <time dateTime={event.occurredAt} title={fullUtc(event.occurredAt)}>
                  {event.time} UTC
                </time>
                <strong>{event.label}</strong>
                <small>{event.detail}</small>
                <code title={`Proof receipt ${event.receipt}`}>#{event.receipt}</code>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ChangeProofPanel() {
  const incident = useIncident();
  const source = changedEvidence(incident);
  const detected = incident.timeline.find((event) => event.label === 'Detected');
  if (!source) return null;
  return (
    <section className="changeProofPanel" aria-labelledby="change-proof-title">
      <div className="changeProofHeading">
        <div>
          <span className="sectionKicker">Cryptographic change proof</span>
          <h2 id="change-proof-title">
            When it changed, what changed, and the evidence that proves it.
          </h2>
        </div>
        <span className="liveRefreshBadge">
          <i aria-hidden="true" />
          {incident.source === 'live' ? 'Live · refreshes every 3s' : 'Evidence-bound demo'}
        </span>
      </div>
      <dl className="proofFacts">
        <div>
          <dt>Change accepted at</dt>
          <dd>
            <time dateTime={source.capturedAt}>{fullUtc(source.capturedAt)}</time>
          </dd>
        </div>
        <div>
          <dt>Registered source</dt>
          <dd>
            {source.kind} · <code>{source.anchor}</code>
          </dd>
        </div>
        <div>
          <dt>Workspace version</dt>
          <dd>
            <code>{source.version}</code>
          </dd>
        </div>
        <div>
          <dt>Immutable snapshot</dt>
          <dd>
            <code>{source.snapshotId}</code>
          </dd>
        </div>
      </dl>
      <div className="proofHash">
        <span>SHA-256 content proof</span>
        <code>{source.contentHash}</code>
      </div>
      {detected && (
        <p>
          Detection receipt <code>#{detected.receipt}</code> binds this snapshot and content hash to
          the append-only incident trace.
        </p>
      )}
    </section>
  );
}

function CertificateCard({
  onRetryVerification,
  verificationRetry,
}: {
  onRetryVerification: () => void;
  verificationRetry: VerificationRetryState;
}) {
  const incident = useIncident();
  const certificate = incident.certificate;
  const pendingApprovals = incident.approvals.filter(
    (approval) => approval.status === 'pending',
  ).length;
  const requiresAttention = incident.status === 'attention';
  const certificateTitle = certificate
    ? 'This packet is consistent within its monitored boundary.'
    : requiresAttention
      ? 'Verification is blocked by a preserved repair conflict.'
      : pendingApprovals > 0
        ? 'Verification is waiting at the human authority boundary.'
        : 'The independent verifier is preparing the monitored boundary.';
  return (
    <aside className="panel certificateCard" aria-labelledby="certificate-title">
      <div className="certificateTopline">
        <span className="verifiedBadge">
          <span aria-hidden="true">{certificate ? '✓' : '…'}</span>{' '}
          {certificate ? 'Verified' : 'Pending'}
        </span>
        <span>{certificate?.shortId ?? 'NO CERTIFICATE'}</span>
      </div>
      <div className="miniSeal" aria-hidden="true">
        V
      </div>
      <span className="sectionKicker">Evidence Integrity Certificate</span>
      <h2 id="certificate-title">{certificateTitle}</h2>
      <blockquote>
        {certificate?.statement ??
          'No certificate is issued until every registered target and protected region passes independent verification.'}
      </blockquote>
      <dl className="certificateFacts">
        <div>
          <dt>Claims</dt>
          <dd>{incident.coverage.claims}</dd>
        </div>
        <div>
          <dt>Targets</dt>
          <dd>
            {incident.coverage.verifiedTargets} / {incident.coverage.targets}
          </dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>{incident.coverage.sources} pinned</dd>
        </div>
        <div>
          <dt>Protected</dt>
          <dd>
            {incident.coverage.verifiedProtectedArtifacts} / {incident.coverage.protectedArtifacts}
          </dd>
        </div>
      </dl>
      <p className="certificateScope">
        Candidate lineage and unregistered prose are explicitly outside this certificate.
      </p>
      {certificate ? (
        <button className="secondaryButton" type="button" onClick={() => window.print()}>
          View certificate record <span aria-hidden="true">↗</span>
        </button>
      ) : requiresAttention || pendingApprovals > 0 ? (
        <div className="certificateHold" role="status">
          <span aria-hidden="true">Ⅱ</span>
          <div>
            <strong>
              {requiresAttention
                ? 'Resolve the repair conflict before verification'
                : `Waiting for ${pendingApprovals} human decision${pendingApprovals === 1 ? '' : 's'}`}
            </strong>
            <small>
              {requiresAttention
                ? `${pendingApprovals} approval${pendingApprovals === 1 ? '' : 's'} remain locked until the durable run recovers.`
                : 'Verification starts automatically after the repair run resumes.'}
            </small>
          </div>
        </div>
      ) : incident.source === 'live' && incident.runId ? (
        <button
          className="secondaryButton"
          type="button"
          onClick={onRetryVerification}
          disabled={verificationRetry === 'running'}
        >
          {verificationRetry === 'running'
            ? 'Re-reading every registered target…'
            : 'Retry independent verification'}
          <span aria-hidden="true">↻</span>
        </button>
      ) : null}
      {verificationRetry === 'error' && (
        <p className="actionError" role="alert">
          Verification could not be completed. No evidence or repair was changed; it is safe to
          retry.
        </p>
      )}
    </aside>
  );
}

function LineageView() {
  const incident = useIncident();
  const source = changedEvidence(incident);
  const { before: beforeValue, after: afterValue } = sourceTransitionValues(incident);
  return (
    <>
      <ViewHeader
        kicker="Registered lineage only"
        title="One cell changed. These are the exact consequences."
        description="The blast radius follows persisted source → claim → artifact anchors. Similar wording and candidate edges never enter automatic repair."
      />

      <section className="lineageCanvas" aria-labelledby="graph-title">
        <div className="graphHeader">
          <div>
            <span className="sectionKicker">Impact graph</span>
            <h2 id="graph-title">
              {incident.coverage.lineagePaths} registered paths · 0 inferred paths
            </h2>
          </div>
          <fieldset className="graphLegend">
            <legend className="srOnly">Graph legend</legend>
            <span>
              <i className="legendSource" /> Evidence
            </span>
            <span>
              <i className="legendClaim" /> Claim
            </span>
            <span>
              <i className="legendArtifact" /> Artifact
            </span>
          </fieldset>
        </div>
        <div className="lineageGraph">
          <div className="graphColumn sourceColumn">
            <span className="columnLabel">Changed source</span>
            <article className="graphNode sourceNode">
              <span className="nodeIcon">S</span>
              <div>
                <small>
                  {source?.kind ?? 'Evidence'} · {source?.anchor ?? 'registered anchor'}
                </small>
                <strong>{source?.label ?? 'Changed evidence'}</strong>
                <span className="valueChange">
                  <s>{beforeValue}</s> → {afterValue}
                </span>
              </div>
            </article>
          </div>
          <div className="graphConnector" aria-hidden="true">
            <span />
          </div>
          <div className="graphColumn claimsColumn">
            <span className="columnLabel">Affected claims</span>
            {incident.claims.map((claim) => (
              <article className="graphNode claimNode" key={claim.id}>
                <span className="nodeIcon">C</span>
                <div>
                  <small>{claim.riskLabel}</small>
                  <strong>{claim.shortLabel}</strong>
                  <span>{claim.targetCount} downstream targets</span>
                </div>
              </article>
            ))}
          </div>
          <div className="graphConnector multiConnector" aria-hidden="true">
            <span />
          </div>
          <div className="graphColumn artifactsColumn">
            <span className="columnLabel">Affected artifacts</span>
            {incident.artifacts.map((artifact) => (
              <article className="graphNode artifactNode" key={artifact.id}>
                <span className={`nodeIcon surface-${artifact.code.toLowerCase()}`}>
                  {artifact.code}
                </span>
                <div>
                  <small>{artifact.surface}</small>
                  <strong>{artifact.name}</strong>
                  <span>
                    {artifact.targetCount} anchors · {artifact.result}
                  </span>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lineageSummary" aria-label="Blast radius summary">
        <div>
          <span>Changed source</span>
          <strong>1</strong>
          <small>semantic delta</small>
        </div>
        <div>
          <span>Affected claims</span>
          <strong>{incident.coverage.affectedClaims}</strong>
          <small>of {incident.coverage.claims} registered</small>
        </div>
        <div>
          <span>Exact paths</span>
          <strong>{incident.coverage.lineagePaths}</strong>
          <small>to {incident.artifacts.length} artifacts</small>
        </div>
        <div>
          <span>Candidate edges used</span>
          <strong>0</strong>
          <small>hard excluded</small>
        </div>
      </section>
    </>
  );
}

function VerificationView({
  onRetryVerification,
  verificationRetry,
}: {
  onRetryVerification: () => void;
  verificationRetry: VerificationRetryState;
}) {
  const incident = useIncident();
  const passedChecks = incident.checks.filter((check) => check.passed).length;
  const pendingApprovals = incident.approvals.filter(
    (approval) => approval.status === 'pending',
  ).length;
  const hasChecks = incident.checks.length > 0;
  const requiresAttention = incident.status === 'attention';
  const traced = incident.timeline.some((event) => event.label.toLowerCase() === 'traced');
  const repaired =
    incident.timeline.some((event) => event.label.toLowerCase() === 'repaired') &&
    !requiresAttention;
  return (
    <>
      <ViewHeader
        kicker="Independent read path"
        title="The repair agent does not grade its own work."
        description="A separate read-only verifier reconstructs the causal state from immutable evidence, re-reads every target, and issues a certificate only at complete coverage."
      />

      <section className="verificationLayout">
        <div className="panel checkPanel">
          <div className="panelHeader">
            <div>
              <span className="sectionKicker">Certificate gates</span>
              <h2>
                {hasChecks
                  ? `${passedChecks} checks passed`
                  : requiresAttention
                    ? 'Verification blocked'
                    : pendingApprovals > 0
                      ? 'Verification waiting'
                      : 'Verifier standing by'}
              </h2>
            </div>
            <span className="verifiedBadge" data-pending={!hasChecks}>
              <span aria-hidden="true">{hasChecks ? '✓' : '…'}</span>{' '}
              {hasChecks ? 'No exceptions' : 'Not started'}
            </span>
          </div>
          {hasChecks ? (
            <ol className="checkList">
              {incident.checks.map((check) => (
                <li key={check.label}>
                  <span className="checkIcon" aria-hidden="true">
                    {check.passed ? '✓' : '!'}
                  </span>
                  <div>
                    <strong>{check.label}</strong>
                    <span>{check.detail}</span>
                  </div>
                  <code>{check.receipt}</code>
                </li>
              ))}
            </ol>
          ) : (
            <div className="verificationWaiting" role="status">
              <div className="verificationWaitingIntro">
                <span aria-hidden="true">Ⅱ</span>
                <div>
                  <strong>Zero checks is a gate, not a failure.</strong>
                  <p>
                    {requiresAttention
                      ? 'The repair run stopped safely on a persisted conflict. The read-only verifier cannot start until recovery succeeds and the remaining human decisions clear.'
                      : 'The read-only verifier cannot grade a run that is still paused for human authority. It starts automatically when the repair run reaches a terminal state.'}
                  </p>
                </div>
              </div>
              <ol className="verificationPrerequisites" aria-label="Verification prerequisites">
                <li data-state={traced ? 'complete' : 'waiting'}>
                  <span aria-hidden="true">{traced ? '✓' : '1'}</span>
                  <div>
                    <strong>Registered paths traced</strong>
                    <small>
                      {traced
                        ? `${incident.coverage.lineagePaths} manifest paths locked`
                        : 'Waiting for causal trace'}
                    </small>
                  </div>
                </li>
                <li data-state={requiresAttention ? 'active' : repaired ? 'complete' : 'waiting'}>
                  <span aria-hidden="true">{repaired ? '✓' : '2'}</span>
                  <div>
                    <strong>Automatic repair run</strong>
                    <small>
                      {requiresAttention
                        ? 'Conflict receipt persisted; operator recovery required'
                        : repaired
                          ? 'Repair run reached terminal state'
                          : 'Waiting for repair run'}
                    </small>
                  </div>
                </li>
                <li data-state={!requiresAttention && pendingApprovals > 0 ? 'active' : 'waiting'}>
                  <span aria-hidden="true">3</span>
                  <div>
                    <strong>Human authority boundary</strong>
                    <small>
                      {requiresAttention
                        ? `${pendingApprovals} decision${pendingApprovals === 1 ? '' : 's'} remain locked behind recovery`
                        : pendingApprovals > 0
                          ? `${pendingApprovals} decision${pendingApprovals === 1 ? '' : 's'} pending`
                          : 'No pending human decisions'}
                    </small>
                  </div>
                </li>
                <li data-state="waiting">
                  <span aria-hidden="true">4</span>
                  <div>
                    <strong>Independent target re-read</strong>
                    <small>Begins automatically after recovery and authority gates clear</small>
                  </div>
                </li>
              </ol>
            </div>
          )}
        </div>
        <CertificateCard
          onRetryVerification={onRetryVerification}
          verificationRetry={verificationRetry}
        />
      </section>

      <CertifiedReferencePanel />

      <section className="panel evidencePanel" aria-labelledby="evidence-title">
        <div className="panelHeader">
          <div>
            <span className="sectionKicker">Causal evidence set</span>
            <h2 id="evidence-title">Every input is immutable and content-addressed</h2>
          </div>
          <span className="appendOnly">SHA-256 bound</span>
        </div>
        <div className="tableScroller">
          <table className="evidenceTable" aria-label="Evidence versions">
            <thead>
              <tr>
                <th scope="col">Registered source</th>
                <th scope="col">Anchor</th>
                <th scope="col">Workspace version</th>
                <th scope="col">Snapshot</th>
                <th scope="col">Captured</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {incident.evidence.map((source) => (
                <tr key={source.id}>
                  <td>
                    <span className="evidenceSource">
                      <strong>{source.label}</strong>
                      <small>{source.kind}</small>
                    </span>
                  </td>
                  <td>
                    <code>{source.anchor}</code>
                  </td>
                  <td>
                    <code>{source.version}</code>
                  </td>
                  <td>
                    <code>{source.snapshot}</code>
                  </td>
                  <td>
                    <time dateTime={source.capturedAt}>{fullUtc(source.capturedAt)}</time>
                  </td>
                  <td>
                    <span className="successCell">
                      <span aria-hidden="true">{source.current ? '✓' : '…'}</span>{' '}
                      {source.current ? 'current' : 'pending verification'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function ViewHeader({
  kicker,
  title,
  description,
}: {
  kicker: string;
  title: string;
  description: string;
}) {
  return (
    <header className="viewHeader">
      <span className="sectionKicker">{kicker}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  );
}
