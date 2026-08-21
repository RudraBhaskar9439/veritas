# ADR 0009: Present incidents as evidence rooms, not generic dashboards

- Status: accepted for pre-browser implementation
- Date: 2026-08-21

## Context

The Command Center has two audiences with almost no patience for setup: the knowledge worker deciding whether to trust an autonomous repair and the hackathon judge deciding whether the product is real. A conventional card dashboard would hide the core differentiator behind navigation and metrics. A polished mockup that cannot expose causal records would be equally weak.

The first viewport must answer five questions immediately: what evidence changed, what consequences were traced, what the agent actually changed, what human work it preserved, and why the certificate is trustworthy. Deeper views must remain usable on a phone, survive refresh, and expose the exact records behind the summary.

## Decision

Veritas uses an “evidence room” Command Center with three persistent views:

1. **Command center** leads with the canonical incident outcome, a six-stage transaction trace, four outcome metrics, selectable before/after claim diffs, deterministic recipes, per-artifact mutation receipts, and the scoped certificate.
2. **Blast radius** renders the registered source → claim → artifact graph as three explicit columns. It shows the exact path and candidate-edge counts so users cannot confuse semantic suggestions with registered lineage.
3. **Verification** shows every certificate gate, immutable source versions, snapshot identifiers, target coverage, protected-region coverage, and the certificate boundary.

The visual language is operational and restrained: deep forest for trusted execution, warm neutral surfaces for evidence, emerald only for verified state, amber for material change or approval, and red only for removed assertions. Typography distinguishes narrative explanation from monospaced receipts and versions. The implementation uses semantic HTML tables, headings, navigation, tabs, a skip link, visible focus states, an ARIA live replay status, reduced-motion handling, and responsive layouts without an image-heavy interface.

The selected view and claim survive refresh through device-local preferences. The “Replay incident” control replays the already persisted canonical trace for demo clarity; it does not pretend to execute a cloud repair. Final production wiring will replace the typed incident fixture with the real incident and verification APIs while preserving the same view model.

A dedicated 1731×909 Veritas social card matches the finished palette and lineage motif for Devpost, repository, and link previews. It contains only the product name, product category, and core promise.

## Consequences

- A judge can understand the complete product loop from the opening screen without narration.
- Exact claim diffs and receipts remain one interaction away instead of being compressed into vanity metrics.
- Certificate scope and candidate exclusions are visible, reducing the risk of an exaggerated “AI guarantees truth” interpretation.
- Unit tests cover navigation, claim selection, refresh recovery, verification evidence, and the replay live region.
- Static accessibility checks, TypeScript, tests, and the production build pass.
- The browser hard gate remains open because the available browser environment blocks local URLs by policy. It must be completed against the hosted Cloud Run URL; the block was not bypassed with another browser surface.
