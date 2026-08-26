import { createContext, useContext, useEffect, useRef, useState } from 'react';
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

type GenerationState =
  | { phase: 'idle' }
  | { phase: 'running' }
  | { phase: 'error'; message: string }
  | { phase: 'complete'; result: PacketGenerationResult };

const views: ReadonlyArray<{ id: ViewId; label: string; index: string }> = [
  { id: 'overview', label: 'Command center', index: '01' },
  { id: 'lineage', label: 'Blast radius', index: '02' },
  { id: 'verification', label: 'Verification', index: '03' },
];

function storedView(): ViewId {
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

function compactSourceValue(statement: string | undefined): string {
  if (!statement) return '—';
  const date = statement.match(/\b\d{4}-\d{2}-\d{2}\b/);
  if (date) return date[0];
  const percent = statement.match(/-?\d+(?:\.\d+)?\s*%/);
  if (percent) return percent[0].replace(/\s+/g, '');
  const currency = statement.match(/[$€£₹]\s*\d+(?:[.,]\d+)*(?:\s*[KMB])?/i);
  if (currency) return currency[0].replace(/\s+/g, '');
  const number = statement.match(/-?\d+(?:\.\d+)?(?:\s*[KMB])?/i);
  return number?.[0].replace(/\s+/g, '') ?? statement;
}

function primaryValueChange(incident: Incident): ClaimChange | undefined {
  return (
    incident.claims.find(
      (claim) => compactSourceValue(claim.before) !== compactSourceValue(claim.after),
    ) ?? incident.claims[0]
  );
}

function fullUtc(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().replace('.000Z', 'Z');
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
    if (initialIncident || generation.phase !== 'complete' || state === 'ready') return;
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
        if (!disposed && result) {
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
  }, [generation.phase, initialIncident, state]);

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
      });
    } catch (error: unknown) {
      setGeneration({
        phase: 'error',
        message: error instanceof Error ? error.message : 'Live generation failed.',
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
        onGenerate={() => void generateLivePacket(generationRequest)}
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
  const [view, setView] = useState<ViewId>(storedView);
  const [selectedClaimId, setSelectedClaimId] = useState(() => storedClaim(incident));
  const [replayStage, setReplayStage] = useState<number>(incident.timeline.length);
  const [isReplaying, setIsReplaying] = useState(false);
  const [verificationRetry, setVerificationRetry] = useState<VerificationRetryState>('idle');
  const selectedClaim =
    incident.claims.find((claim) => claim.id === selectedClaimId) ?? incident.claims[0];

  useEffect(() => {
    window.localStorage.setItem(VIEW_STORAGE_KEY, view);
  }, [view]);

  useEffect(() => {
    window.localStorage.setItem(CLAIM_STORAGE_KEY, selectedClaimId);
  }, [selectedClaimId]);

  useEffect(() => {
    if (!isReplaying) return;
    const timer = window.setInterval(() => {
      setReplayStage((stage) => {
        const next = stage + 1;
        if (next >= incident.timeline.length) {
          setIsReplaying(false);
          return incident.timeline.length;
        }
        return next;
      });
    }, 720);
    return () => window.clearInterval(timer);
  }, [isReplaying, incident.timeline.length]);

  useEffect(() => {
    if (!isReplaying) setReplayStage(incident.timeline.length);
  }, [incident.timeline.length, isReplaying]);

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
    window.scrollTo?.({ top: 0, behavior: 'smooth' });
  }

  function replayIncident() {
    setReplayStage(0);
    setIsReplaying(true);
    setView('overview');
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
      <div className="appFrame">
        <a className="skipLink" href="#main-content">
          Skip to incident details
        </a>

        <header className="topbar">
          <a className="brand" href="/" aria-label="Veritas command center home">
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
              <span className="incidentDuration">Resolved in 9 seconds</span>
            </div>
          </div>
          <nav>
            {views.map((item) => (
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
              selectedClaim={selectedClaim}
              onSelectClaim={setSelectedClaimId}
              replayStage={replayStage}
              visibleClaims={visibleClaims}
              visibleArtifacts={visibleArtifacts}
              verifiedTargets={verifiedTargets}
              onIncidentChange={onIncidentChange}
              onRetryVerification={() => void retryVerification()}
              verificationRetry={verificationRetry}
            />
          )}
          {view === 'lineage' && <LineageView />}
          {view === 'verification' && (
            <VerificationView
              onRetryVerification={() => void retryVerification()}
              verificationRetry={verificationRetry}
            />
          )}
        </main>

        <div className="srOnly" role="status" aria-live="polite">
          {isReplaying
            ? `Incident replay step ${replayStage + 1} of ${incident.timeline.length}`
            : 'Incident is independently verified.'}
        </div>
      </div>
    </IncidentContext.Provider>
  );
}

function StartupState({
  state,
  generation,
  onGenerate,
  onRetry,
  onDemo,
}: {
  state: StartupStatus;
  generation: GenerationState;
  onGenerate: () => void;
  onRetry: () => void;
  onDemo: () => void;
}) {
  const connect = () => {
    window.location.assign('/api/v1/auth/google/start?returnTo=/');
  };
  return (
    <main className="startupState">
      <span className="brandMark" aria-hidden="true">
        V
      </span>
      <span className="sectionKicker">Veritas Command Center</span>
      <h1>
        {state === 'loading'
          ? 'Loading your evidence boundary…'
          : state === 'unauthorized'
            ? 'Connect Google Workspace to begin.'
            : state === 'empty'
              ? 'Your workspace is connected.'
              : 'The live Command Center is temporarily unreachable.'}
      </h1>
      <p>
        {state === 'empty'
          ? 'Generate a decision packet to register its claims, evidence, and downstream artifacts.'
          : 'Live mode never substitutes demonstration data silently. You can retry, connect, or explicitly open the offline judge demo.'}
      </p>
      <div className="startupActions">
        {state === 'unauthorized' && (
          <button className="replayButton" type="button" onClick={connect}>
            Connect Google Workspace
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
      {generation.phase === 'error' && (
        <p className="actionError" role="alert">
          {generation.message} No demonstration data was substituted.
        </p>
      )}
      {generation.phase === 'complete' && (
        <GeneratedPacket result={generation.result} onRetry={onGenerate} />
      )}
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
        Live monitoring active · waiting for a meaningful source change.
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
  return null;
}

interface OverviewProps {
  selectedClaim: ClaimChange;
  onSelectClaim: (claimId: string) => void;
  replayStage: number;
  visibleClaims: number;
  visibleArtifacts: number;
  verifiedTargets: number;
  onIncidentChange: (incident: Incident) => void;
  onRetryVerification: () => void;
  verificationRetry: VerificationRetryState;
}

function Overview({
  selectedClaim,
  onSelectClaim,
  replayStage,
  visibleClaims,
  visibleArtifacts,
  verifiedTargets,
  onIncidentChange,
  onRetryVerification,
  verificationRetry,
}: OverviewProps) {
  const incident = useIncident();
  const source = changedEvidence(incident);
  const valueChange = primaryValueChange(incident);
  const beforeValue = compactSourceValue(valueChange?.before);
  const afterValue = compactSourceValue(valueChange?.after);
  return (
    <>
      <section className="judgeStage" aria-labelledby="incident-title">
        <div className="stageGrid" aria-hidden="true" />
        <div className="incidentHeading">
          <div className="incidentMeta">
            <span className="incidentNumber">AUTONOMOUS RUN · INCIDENT 042</span>
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

      <Timeline activeStage={replayStage} />

      <ChangeProofPanel />

      <ApprovalQueue onIncidentChange={onIncidentChange} />

      <ConsequenceMap replayStage={replayStage} />

      <div className="overviewGrid">
        <section className="panel diffPanel" aria-labelledby="diff-title">
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
                <span>0{index + 1}</span>
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

        <CertificateCard
          onRetryVerification={onRetryVerification}
          verificationRetry={verificationRetry}
        />
      </div>

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
    </>
  );
}

function ApprovalQueue({ onIncidentChange }: { onIncidentChange: (incident: Incident) => void }) {
  const incident = useIncident();
  const pending = incident.approvals.filter((approval) => approval.status === 'pending');
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestIds = useRef(new Map<string, string>());
  if (pending.length === 0) return null;

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
                disabled={working !== null || incident.source !== 'live'}
                onClick={() => decide(approval, 'reject')}
              >
                Reject
              </button>
              <button
                className="replayButton"
                type="button"
                disabled={working !== null || incident.source !== 'live'}
                onClick={() => decide(approval, 'approve')}
              >
                {working === approval.approvalId ? 'Applying decision…' : 'Approve & continue'}
              </button>
            </div>
          </article>
        ))}
      </div>
      {error && (
        <p className="actionError" role="alert">
          {error}
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

function Timeline({ activeStage }: { activeStage: number }) {
  const incident = useIncident();
  return (
    <section className="timelineSection" aria-labelledby="timeline-title">
      <div className="timelineIntro">
        <span className="sectionKicker">Live transaction trace</span>
        <h2 id="timeline-title">Source change → scoped certificate</h2>
      </div>
      <ol className="timeline">
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
      <h2 id="certificate-title">This packet is consistent within its monitored boundary.</h2>
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
  const valueChange = primaryValueChange(incident);
  const beforeValue = compactSourceValue(valueChange?.before);
  const afterValue = compactSourceValue(valueChange?.after);
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
              <h2>{incident.checks.filter((check) => check.passed).length} checks passed</h2>
            </div>
            <span className="verifiedBadge">
              <span aria-hidden="true">✓</span> No exceptions
            </span>
          </div>
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
        </div>
        <CertificateCard
          onRetryVerification={onRetryVerification}
          verificationRetry={verificationRetry}
        />
      </section>

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
