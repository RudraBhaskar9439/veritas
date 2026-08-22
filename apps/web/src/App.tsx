import { useEffect, useMemo, useState } from 'react';
import { type ClaimChange, incident, type ViewId } from './incident';

const VIEW_STORAGE_KEY = 'veritas.command-center.view';
const CLAIM_STORAGE_KEY = 'veritas.command-center.claim';

const views: ReadonlyArray<{ id: ViewId; label: string; index: string }> = [
  { id: 'overview', label: 'Command center', index: '01' },
  { id: 'lineage', label: 'Blast radius', index: '02' },
  { id: 'verification', label: 'Verification', index: '03' },
];

function storedView(): ViewId {
  const value = window.localStorage.getItem(VIEW_STORAGE_KEY);
  return views.some((view) => view.id === value) ? (value as ViewId) : 'overview';
}

function storedClaim(): string {
  const value = window.localStorage.getItem(CLAIM_STORAGE_KEY);
  return incident.claims.some((claim) => claim.id === value)
    ? (value ?? '')
    : incident.claims[0].id;
}

export function App() {
  const [view, setView] = useState<ViewId>(storedView);
  const [selectedClaimId, setSelectedClaimId] = useState(storedClaim);
  const [replayStage, setReplayStage] = useState<number>(incident.timeline.length);
  const [isReplaying, setIsReplaying] = useState(false);
  const selectedClaim = useMemo(
    () => incident.claims.find((claim) => claim.id === selectedClaimId) ?? incident.claims[0],
    [selectedClaimId],
  );

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
  }, [isReplaying]);

  function chooseView(next: ViewId) {
    setView(next);
    window.scrollTo?.({ top: 0, behavior: 'smooth' });
  }

  function replayIncident() {
    setReplayStage(0);
    setIsReplaying(true);
    setView('overview');
  }

  const visibleClaims = replayStage >= 2 ? incident.claims.length : 0;
  const visibleArtifacts = replayStage >= 3 ? incident.artifacts.length : 0;
  const verifiedTargets = replayStage >= 4 ? incident.coverage.targets : 0;

  return (
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
          <span className="environment">Evidence-bound replay · Q3 workspace</span>
          <span className="systemStatus">
            <span className="pulseDot" aria-hidden="true" />
            Runtime ready
          </span>
          <button className="replayButton" type="button" onClick={replayIncident}>
            <span aria-hidden="true">↻</span>
            {isReplaying ? 'Replaying incident' : 'Replay incident'}
          </button>
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
          <strong>Aug 21 · 10:42 UTC</strong>
          <span>6 immutable evidence versions</span>
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
          />
        )}
        {view === 'lineage' && <LineageView />}
        {view === 'verification' && <VerificationView />}
      </main>

      <div className="srOnly" role="status" aria-live="polite">
        {isReplaying
          ? `Incident replay step ${replayStage + 1} of ${incident.timeline.length}`
          : 'Incident is independently verified.'}
      </div>
    </div>
  );
}

interface OverviewProps {
  selectedClaim: ClaimChange;
  onSelectClaim: (claimId: string) => void;
  replayStage: number;
  visibleClaims: number;
  visibleArtifacts: number;
  verifiedTargets: number;
}

function Overview({
  selectedClaim,
  onSelectClaim,
  replayStage,
  visibleClaims,
  visibleArtifacts,
  verifiedTargets,
}: OverviewProps) {
  return (
    <>
      <section className="judgeStage" aria-labelledby="incident-title">
        <div className="stageGrid" aria-hidden="true" />
        <div className="incidentHeading">
          <div className="incidentMeta">
            <span className="incidentNumber">AUTONOMOUS RUN · INCIDENT 042</span>
            <span className="severity">Material evidence change</span>
          </div>
          <h1 id="incident-title">
            One number changed. <span>Nine consequences repaired.</span>
          </h1>
          <p>
            A registered Sheet value moved from <strong>4%</strong> to <strong>9%</strong>. Veritas
            traced the exact blast radius, repaired only owned claim anchors, preserved the
            CFO&apos;s paragraph, and proved the result through a separate read path.
          </p>
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
              <i aria-hidden="true">S</i> Google Sheets
            </span>
            <span className="sourceLive">
              <i aria-hidden="true" /> source event
            </span>
          </div>
          <div className="sourceAnchor">
            <span>REGISTERED SOURCE</span>
            <code>Metrics!B17</code>
          </div>
          <div className="valueTransition">
            <span className="srOnly">Source value changed from 4 percent to 9 percent</span>
            <s>4%</s>
            <span aria-hidden="true">→</span>
            <strong>9%</strong>
          </div>
          <div className="sourceClock">
            <span>
              <small>Detected</small>10:42:07
            </span>
            <span>
              <small>Certified</small>10:42:16
            </span>
          </div>
          <div className="scopeStamp" data-visible={replayStage >= 5}>
            <span aria-hidden="true">✓</span>
            <div>
              <strong>
                {replayStage >= 5
                  ? 'Scoped certificate issued'
                  : 'Independent verification running'}
              </strong>
              <small>{incident.certificate.shortId} · 36 checks</small>
            </div>
          </div>
        </div>
      </section>

      <section className="metricStrip" aria-label="Incident outcome">
        <Metric value={`${visibleClaims}`} label="Claims changed" detail="of 8 monitored" />
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

        <CertificateCard />
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

function ConsequenceMap({ replayStage }: { replayStage: number }) {
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
              <small>Google Sheets · Metrics!B17</small>
              <strong>Customer churn</strong>
              <span>
                <s>4%</s> → 9%
              </span>
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
          <span>9 exact paths</span>
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
          <i aria-hidden="true">✓</i> 13/13 targets independently verified
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
                <span>{event.time}</span>
                <strong>{event.label}</strong>
                <small>{event.detail}</small>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CertificateCard() {
  return (
    <aside className="panel certificateCard" aria-labelledby="certificate-title">
      <div className="certificateTopline">
        <span className="verifiedBadge">
          <span aria-hidden="true">✓</span> Verified
        </span>
        <span>{incident.certificate.shortId}</span>
      </div>
      <div className="miniSeal" aria-hidden="true">
        V
      </div>
      <span className="sectionKicker">Evidence Integrity Certificate</span>
      <h2 id="certificate-title">This packet is consistent within its monitored boundary.</h2>
      <blockquote>{incident.certificate.statement}</blockquote>
      <dl className="certificateFacts">
        <div>
          <dt>Claims</dt>
          <dd>8 / 8</dd>
        </div>
        <div>
          <dt>Targets</dt>
          <dd>13 / 13</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>6 pinned</dd>
        </div>
        <div>
          <dt>Protected</dt>
          <dd>5 / 5</dd>
        </div>
      </dl>
      <p className="certificateScope">
        Candidate lineage and unregistered prose are explicitly outside this certificate.
      </p>
      <button className="secondaryButton" type="button" onClick={() => window.print()}>
        View certificate record <span aria-hidden="true">↗</span>
      </button>
    </aside>
  );
}

function LineageView() {
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
            <h2 id="graph-title">9 registered paths · 0 inferred paths</h2>
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
                <small>Google Sheets · Metrics!B17</small>
                <strong>Customer churn</strong>
                <span className="valueChange">
                  <s>4%</s> → 9%
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
          <strong>4</strong>
          <small>of 8 registered</small>
        </div>
        <div>
          <span>Exact paths</span>
          <strong>9</strong>
          <small>to 5 artifacts</small>
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

function VerificationView() {
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
              <h2>36 checks passed</h2>
            </div>
            <span className="verifiedBadge">
              <span aria-hidden="true">✓</span> No exceptions
            </span>
          </div>
          <ol className="checkList">
            {incident.checks.map((check) => (
              <li key={check.label}>
                <span className="checkIcon" aria-hidden="true">
                  ✓
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
        <CertificateCard />
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
                    <span className="successCell">
                      <span aria-hidden="true">✓</span> current
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
