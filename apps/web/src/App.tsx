const foundationChecks = [
  { label: 'Claim Manifest', state: 'contracted' },
  { label: 'Runtime services', state: 'healthy' },
  { label: 'Google Cloud foundation', state: 'defined' },
] as const;

export function App() {
  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Veritas home">
          <span className="brandMark" aria-hidden="true">
            V
          </span>
          <span>Veritas</span>
        </a>
        <span className="phaseBadge">Phase 1 foundation</span>
      </header>

      <section className="hero" aria-labelledby="hero-title">
        <p className="eyebrow">Continuous evidence integrity</p>
        <h1 id="hero-title">AI created the work. Veritas keeps it true.</h1>
        <p className="lede">
          The production foundation is active. Registered claims, durable services, and cloud
          infrastructure are being built behind one verifiable operating loop.
        </p>
      </section>

      <section className="statusGrid" aria-label="Foundation status">
        {foundationChecks.map((check) => (
          <article className="statusItem" key={check.label}>
            <span className="statusDot" aria-hidden="true" />
            <div>
              <h2>{check.label}</h2>
              <p>{check.state}</p>
            </div>
          </article>
        ))}
      </section>

      <section className="loop" aria-labelledby="loop-title">
        <div>
          <p className="eyebrow">Hard product invariant</p>
          <h2 id="loop-title">No certificate without complete verification.</h2>
        </div>
        <ol>
          <li>Detect</li>
          <li>Trace impact</li>
          <li>Repair minimally</li>
          <li>Verify independently</li>
        </ol>
      </section>
    </main>
  );
}
