import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { demoIncident, type Incident } from './incident';

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
  window.scrollTo = vi.fn();
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('Veritas command center', () => {
  it('leads with the complete verified incident outcome', () => {
    render(<App initialIncident={demoIncident} />);

    expect(
      screen.getByRole('heading', { name: 'One number changed. Nine consequences repaired.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('13/13')).toBeInTheDocument();
    expect(screen.getByText('0', { selector: '.metric > strong' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));
    expect(
      screen.getByText(/All monitored claims in this Decision Packet are consistent/),
    ).toBeInTheDocument();
  });

  it('makes the registered blast radius legible in the opening view', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Proof ledger' }));

    expect(
      screen.getByRole('heading', {
        name: 'The source moved. Veritas knew exactly what it owned.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('02 · 4 affected claims')).toBeInTheDocument();
    expect(screen.getByText('03 · 5 repaired artifacts')).toBeInTheDocument();
    expect(screen.getByText('0 inferred paths')).toBeInTheDocument();
  });

  it('never mistakes the quarter label for a changed source value', () => {
    const comparisonIncident: Incident = {
      ...demoIncident,
      claims: [demoIncident.claims[1]],
      evidence: demoIncident.evidence.map((source) => ({
        ...source,
        changed: source.id === 'previous-churn',
      })),
    };
    const { container } = render(<App initialIncident={comparisonIncident} />);

    const transition = container.querySelector('.valueTransition');
    expect(transition).toHaveTextContent('prior');
    expect(transition).toHaveTextContent('current');
    expect(transition).not.toHaveTextContent('3');
    expect(screen.getByText('Metrics!B16')).toBeInTheDocument();
  });

  it('keeps exact percentage values for the primary monitored source', () => {
    const { container } = render(<App initialIncident={demoIncident} />);

    const transition = container.querySelector('.valueTransition');
    expect(transition).toHaveTextContent('4%');
    expect(transition).toHaveTextContent('9%');
  });

  it('shows an exact deterministic diff for every affected claim', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Proof ledger' }));

    fireEvent.click(screen.getByRole('tab', { name: /Retention target/ }));
    expect(screen.getByText('The retention target has been achieved.')).toBeInTheDocument();
    expect(screen.getByText('The retention target has not been achieved.')).toBeInTheDocument();
    expect(screen.getByText('churn_lte_target_5_percent@1')).toBeInTheDocument();
  });

  it('recovers the selected command-center view after a refresh', () => {
    const first = render(<App initialIncident={demoIncident} />);
    fireEvent.click(screen.getByRole('button', { name: 'Blast radius' }));
    expect(
      screen.getByRole('heading', { name: 'One cell changed. These are the exact consequences.' }),
    ).toBeInTheDocument();
    first.unmount();

    render(<App initialIncident={demoIncident} />);
    expect(
      screen.getByRole('heading', { name: 'One cell changed. These are the exact consequences.' }),
    ).toBeInTheDocument();
  });

  it('exposes the independent checks and immutable evidence set', () => {
    render(<App initialIncident={demoIncident} />);
    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));

    expect(
      screen.getByRole('heading', { name: 'The repair agent does not grade its own work.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('7 checks passed')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Evidence versions' })).toBeInTheDocument();
    expect(screen.getByText('Metrics!B17')).toBeInTheDocument();
  });

  it('shows exact change time and cryptographic proof receipts', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Live run' }));

    expect(
      screen.getByRole('heading', {
        name: 'When it changed, what changed, and the evidence that proves it.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('2026-08-21T10:42:07Z', { selector: 'time' })).toBeInTheDocument();
    expect(screen.getByText(demoIncident.evidence[0].contentHash)).toBeInTheDocument();
    expect(screen.getAllByText(`#${demoIncident.timeline[0].receipt}`)).toHaveLength(2);
    expect(screen.getByText('Certified after 9s')).toBeInTheDocument();
    expect(screen.queryByText('Resolved in 9 seconds')).toBeNull();
  });

  it('renders only persisted receipts in the live execution observatory', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Live run' }));

    const executionLog = screen.getByRole('log', { name: 'Live signed execution receipts' });
    expect(executionLog).toHaveTextContent('DETECTED');
    expect(executionLog).toHaveTextContent(demoIncident.timeline[0].detail);
    expect(executionLog).toHaveTextContent(demoIncident.timeline[0].receipt.slice(0, 10));
    expect(executionLog).toHaveTextContent('no simulated log lines');
  });

  it('makes the bounded Gemini decision and authority limits judge-visible', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Live run' }));

    expect(
      screen.getByRole('heading', { name: 'Source truth → repaired consequences → proof' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Gemini reviewed')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: 'Gemini interprets the risk. Policy owns authority.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(demoIncident.agentReview.rationale)).toBeInTheDocument();
    expect(screen.getByText(`receipt · ${demoIncident.agentReview.receipt}`)).toBeInTheDocument();
    expect(screen.getByText('Expand registered scope')).toBeInTheDocument();
    expect(screen.getByText('Approve decision changes')).toBeInTheDocument();
    expect(screen.getByText('Issue the certificate')).toBeInTheDocument();
  });

  it('proves the Q3 scenario is supplied through the reusable packet contract', () => {
    render(<App initialIncident={demoIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'Architecture' }));

    expect(
      screen.getByRole('heading', { name: 'The Q3 scenario is input—not application code.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('POST /api/v1/packets')).toBeInTheDocument();
    expect(screen.getByText(demoIncident.packetId)).toBeInTheDocument();
    expect(screen.getByText('6 sources · 8 claims · 13 targets')).toBeInTheDocument();
  });

  it('can replay the incident through an announced live region', () => {
    render(<App initialIncident={demoIncident} />);
    fireEvent.click(screen.getByRole('button', { name: 'Replay incident' }));

    expect(screen.getByRole('status')).toHaveTextContent('Incident replay step 1 of 6');
    expect(screen.getByRole('button', { name: 'Replaying incident' })).toBeInTheDocument();
  });

  it('never substitutes demo data silently when the live API is unavailable', async () => {
    vi.spyOn(window, 'fetch').mockRejectedValue(new Error('offline'));
    render(<App />);

    expect(
      await screen.findByRole('heading', {
        name: 'The live Command Center is temporarily unreachable.',
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: 'One number changed. Nine consequences repaired.' }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Open offline judge demo' }));
    expect(
      screen.getByRole('heading', { name: 'One number changed. Nine consequences repaired.' }),
    ).toBeInTheDocument();
  });

  it('creates real evidence before generating and monitoring a live packet', async () => {
    const sources = [
      {
        sourceId: 'src-churn',
        kind: 'google_sheet',
        resourceId: 'real-sheet',
        anchor: 'Metrics!B17',
        version: '7',
        value: 0.04,
      },
      {
        sourceId: 'src-launch',
        kind: 'google_doc',
        resourceId: 'real-doc',
        anchor: 'launch-date',
        version: '9',
        value: '2026-10-15',
      },
    ];
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response('null'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ sources })))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            manifest: {
              packetId: 'packet-q3-executive-review',
              sources,
              artifacts: [
                {
                  artifactId: 'board-brief',
                  kind: 'google_slides',
                  resourceId: 'real-slides',
                },
                {
                  artifactId: 'acquisition-task',
                  kind: 'google_task',
                  resourceId: 'real-task',
                },
              ],
            },
            checksum: 'a'.repeat(64),
            reused: false,
          }),
        ),
      )
      .mockResolvedValue(new Response('null'));
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Generate real Workspace packet' }));
    expect(
      await screen.findByRole('heading', { name: 'Decision packet created and monitored.' }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.slice(0, 3).map(([url]) => url)).toEqual([
      '/api/v1/command-center/incidents/latest',
      '/api/v1/evidence/bootstrap',
      '/api/v1/packets',
    ]);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/command-center/incidents/latest',
        expect.objectContaining({
          headers: expect.objectContaining({ 'X-Veritas-Refresh': 'packet-watch' }),
        }),
      ),
    );
    expect(screen.getByRole('link', { name: /src-churn/ })).toHaveAttribute(
      'href',
      'https://docs.google.com/spreadsheets/d/real-sheet/edit',
    );
    expect(screen.getByRole('link', { name: /acquisition-task/ })).toHaveAttribute(
      'href',
      'https://tasks.google.com/',
    );
  });

  it('opens a detected incident automatically after live packet generation', async () => {
    const liveIncident: Incident = { ...demoIncident, packetId: 'packet-live', source: 'live' };
    const sources = [
      {
        sourceId: 'src-churn',
        kind: 'google_sheet',
        resourceId: 'real-sheet',
        anchor: 'Metrics!B17',
        version: '7',
        value: 0.04,
      },
    ];
    vi.spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response('null'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ sources })))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            manifest: {
              packetId: 'packet-live',
              sources,
              artifacts: [],
            },
            checksum: 'c'.repeat(64),
            reused: false,
          }),
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(liveIncident)));
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Generate real Workspace packet' }));

    expect(
      await screen.findByRole('heading', {
        name: 'One number changed. Nine consequences repaired.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('13/13')).toBeInTheDocument();
  });

  it('can create a fresh isolated evidence boundary after an incident', async () => {
    const liveIncident: Incident = { ...demoIncident, source: 'live' };
    const sources = [
      {
        sourceId: 'src-churn',
        kind: 'google_sheet',
        resourceId: 'fresh-sheet',
        anchor: 'Metrics!B17',
        version: '1',
        value: 0.04,
      },
    ];
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('12345678-1234-4000-8000-123456789abc');
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ sources })))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            manifest: {
              packetId: 'packet-q3-executive-review-123456781234',
              sources,
              artifacts: [],
            },
            checksum: 'b'.repeat(64),
            reused: false,
          }),
        ),
      )
      .mockResolvedValueOnce(new Response('null'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ sources })))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            manifest: {
              packetId: 'packet-q3-executive-review-123456781234',
              sources,
              artifacts: [],
            },
            checksum: 'b'.repeat(64),
            reused: true,
          }),
        ),
      )
      .mockResolvedValue(new Response('null'));
    render(<App initialIncident={liveIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'New monitored packet' }));
    expect(
      await screen.findByRole('heading', { name: 'Decision packet created and monitored.' }),
    ).toBeInTheDocument();
    const bootstrapBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const packetBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(bootstrapBody.requestId).toBe('generate-q3-executive-review-v1-123456781234-sources');
    expect(packetBody.blueprint.packetId).toBe('packet-q3-executive-review-123456781234');
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/command-center/incidents/latest',
        expect.objectContaining({
          headers: expect.objectContaining({ 'X-Veritas-Refresh': 'packet-watch' }),
        }),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Verify idempotent replay' }));
    expect(await screen.findByText(/Idempotent replay confirmed/)).toBeInTheDocument();
    const replayBootstrapBody = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
    const replayPacketBody = JSON.parse(String(fetchMock.mock.calls[4][1]?.body));
    expect(replayBootstrapBody.requestId).toBe(bootstrapBody.requestId);
    expect(replayPacketBody.blueprint.packetId).toBe(packetBody.blueprint.packetId);
  });

  it('retries a failed fresh packet with the same idempotency identity', async () => {
    const liveIncident: Incident = { ...demoIncident, source: 'live' };
    const sources = [
      {
        sourceId: 'src-churn',
        kind: 'google_sheet',
        resourceId: 'retry-sheet',
        anchor: 'Metrics!B17',
        version: '1',
        value: 0.04,
      },
    ];
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('abcdef12-1234-4000-8000-123456789abc');
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'Workspace dependency unavailable' }), {
          status: 503,
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ sources })))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            manifest: {
              packetId: 'packet-q3-executive-review-abcdef121234',
              sources,
              artifacts: [],
            },
            checksum: 'c'.repeat(64),
            reused: false,
          }),
        ),
      )
      .mockResolvedValue(new Response('null'));
    render(<App initialIncident={liveIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'New monitored packet' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Workspace dependency unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Generate real Workspace packet' }));
    expect(
      await screen.findByRole('heading', { name: 'Decision packet created and monitored.' }),
    ).toBeInTheDocument();

    const firstAttempt = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const retriedAttempt = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    const retriedPacket = JSON.parse(String(fetchMock.mock.calls[2][1]?.body));
    expect(retriedAttempt.requestId).toBe(firstAttempt.requestId);
    expect(retriedPacket.blueprint.packetId).toBe('packet-q3-executive-review-abcdef121234');
  });

  it('uses one server-side action for approval, continuation, and verification', async () => {
    const pending: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'awaiting_approval',
      certificate: null,
      approvals: [
        {
          approvalId: 'approval-1',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'retention-target',
          claimLabel: 'Retention target',
          status: 'pending',
          reason: null,
        },
      ],
    };
    const completed: Incident = { ...demoIncident, source: 'live' };
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ run: { status: 'completed' } })))
      .mockResolvedValueOnce(new Response(JSON.stringify(completed)));
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001');
    render(<App initialIncident={pending} />);

    fireEvent.click(screen.getByRole('button', { name: 'Repair desk' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve & continue' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/command-center/incidents/${pending.id}/runs/${pending.runId}/approvals/approval-1`,
    );
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/command-center/incidents/latest');
    fireEvent.click(screen.getByRole('button', { name: 'Command center' }));
    expect(
      await screen.findByRole('heading', {
        name: 'One number changed. Nine consequences repaired.',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Decision-changing consequences need your approval')).toBeNull();
  });

  it('reuses the same approval receipt when a continuation is retried', async () => {
    const pending: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'awaiting_approval',
      certificate: null,
      approvals: [
        {
          approvalId: 'approval-retry',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'retention-target',
          claimLabel: 'Retention target',
          status: 'pending',
          reason: null,
        },
      ],
    };
    const completed: Incident = { ...demoIncident, source: 'live' };
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(pending)))
      .mockResolvedValueOnce(new Response(JSON.stringify({ run: { status: 'completed' } })))
      .mockResolvedValueOnce(new Response(JSON.stringify(completed)));
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000099');
    render(<App initialIncident={pending} />);

    fireEvent.click(screen.getByRole('button', { name: 'Repair desk' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve & continue' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('request receipt is preserved');
    fireEvent.click(screen.getByRole('button', { name: 'Approve & continue' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    const firstBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const retryBody = JSON.parse(String(fetchMock.mock.calls[2][1]?.body));
    expect(firstBody.requestId).toBe('00000000-0000-4000-8000-000000000099');
    expect(retryBody.requestId).toBe(firstBody.requestId);
  });

  it('keeps human decisions locked until automatic work reaches the authority boundary', () => {
    const repairing: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'repairing',
      certificate: null,
      approvals: [
        {
          approvalId: 'approval-locked',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'retention-target',
          claimLabel: 'Retention target',
          status: 'pending',
          reason: null,
        },
      ],
    };
    render(<App initialIncident={repairing} />);

    fireEvent.click(screen.getByRole('button', { name: 'Repair desk' }));
    expect(screen.getByRole('button', { name: 'Approve & continue' })).toBeDisabled();
    expect(screen.getByText(/Decisions unlock only/)).toHaveTextContent(
      'Decisions unlock only after the durable run reaches the human authority boundary',
    );
  });

  it('exposes an audited replay for a quarantined live operation', async () => {
    const repairing: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'attention',
      runId: null,
      certificate: null,
      agentReview: null,
      approvals: [],
    };
    const deadLetter = {
      operationId: 'op-dead-letter',
      kind: 'drive.process',
      correlationId: 'drive-notification:watch:42',
      attempt: 5,
      maxAttempts: 5,
      errorCode: 'gemini_review_unavailable',
      diagnosticFingerprint: '786295b2ce2b3c9877f7a432',
      replayOf: null,
      packetIds: [repairing.packetId],
      updatedAt: '2026-08-26T07:43:14Z',
    };
    const unrelatedDeadLetter = {
      ...deadLetter,
      operationId: 'op-unrelated-packet',
      errorCode: 'unrelated_failure',
      packetIds: ['another-packet'],
      updatedAt: '2026-08-26T07:44:14Z',
    };
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify([unrelatedDeadLetter, deadLetter])))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ operation: { status: 'queued' }, reused: false })),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(repairing)));
    render(<App initialIncident={repairing} />);

    fireEvent.click(screen.getByRole('button', { name: 'Repair desk' }));
    expect(
      await screen.findByRole('heading', {
        name: 'The agent stopped safely. Recovery needs an operator.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('gemini review unavailable')).toBeInTheDocument();
    expect(screen.queryByText('unrelated failure')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Replay safely' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/v1/operations/dead-letters/op-dead-letter/replay',
    );
    expect(await screen.findByText(/Audited replay queued/)).toHaveTextContent(
      'Existing receipts and completed writes remain preserved',
    );
  });

  it('refreshes every live graph from the latest incident without a page reload', async () => {
    vi.useFakeTimers();
    const initial: Incident = {
      ...demoIncident,
      source: 'live',
      headline: 'Old live incident',
    };
    const refreshed: Incident = {
      ...initial,
      headline: 'New source change arrived',
      coverage: { ...initial.coverage, lineagePaths: 12 },
    };
    vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify(refreshed)));
    render(<App initialIncident={initial} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(screen.getByRole('heading', { name: 'New source change arrived' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Blast radius' }));
    expect(screen.getByText('12 registered paths · 0 inferred paths')).toBeInTheDocument();
  });

  it('streams a newly persisted receipt into the graph without a page reload', async () => {
    vi.useFakeTimers();
    const initial: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'repairing',
      certificate: null,
      checks: [],
      timeline: demoIncident.timeline.slice(0, 2),
    };
    const refreshed: Incident = {
      ...initial,
      timeline: [
        ...initial.timeline,
        {
          time: '10:42:10',
          occurredAt: '2026-08-21T10:42:10Z',
          label: 'Planned',
          detail: '13 typed operations persisted',
          receipt: 'plan0b9a4c2d18ef',
        },
      ],
    };
    vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify(refreshed)));
    render(<App initialIncident={initial} />);

    fireEvent.click(screen.getByRole('button', { name: 'Live run' }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole('log')).not.toHaveTextContent('13 typed operations persisted');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(460);
    });
    expect(screen.getByRole('log')).toHaveTextContent('13 typed operations persisted');
    expect(screen.getByRole('img', { name: /Live causal graph/ })).toBeInTheDocument();
  });

  it('explains why checks are gated while human approvals are pending', () => {
    const pending: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'awaiting_approval',
      certificate: null,
      checks: [],
      coverage: {
        ...demoIncident.coverage,
        verifiedTargets: 0,
        verifiedProtectedArtifacts: 0,
      },
      approvals: [
        {
          approvalId: 'approval-1',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'retention-target',
          claimLabel: 'Retention target',
          status: 'pending',
          reason: null,
        },
        {
          approvalId: 'approval-2',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'acquisition',
          claimLabel: 'Acquisition spend',
          status: 'pending',
          reason: null,
        },
      ],
    };
    render(<App initialIncident={pending} />);
    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));

    expect(screen.getByRole('heading', { name: 'Verification waiting' })).toBeInTheDocument();
    expect(screen.getByText('Zero checks is a gate, not a failure.')).toBeInTheDocument();
    expect(screen.getByText('2 decisions pending')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: 'Verification is waiting at the human authority boundary.',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry independent verification' })).toBeNull();
  });

  it('shows a preserved run conflict before approvals or verification', () => {
    const attention: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'attention',
      certificate: null,
      checks: [],
      approvals: [
        {
          approvalId: 'approval-conflict',
          planId: demoIncident.id,
          runId: demoIncident.runId,
          claimId: 'acquisition',
          claimLabel: 'Acquisition spend',
          status: 'pending',
          reason: null,
        },
      ],
    };
    render(<App initialIncident={attention} />);

    fireEvent.click(screen.getByRole('button', { name: 'Live run' }));
    expect(screen.getByText('Attention · run conflict')).toBeInTheDocument();
    expect(screen.getByText('Run conflict requires review')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /repairs blocked by conflict/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));
    expect(screen.getByRole('heading', { name: 'Verification blocked' })).toBeInTheDocument();
    expect(
      screen.getByText('Conflict receipt persisted; operator recovery required'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        name: 'Verification is blocked by a preserved repair conflict.',
      }),
    ).toBeInTheDocument();
  });

  it('retries independent verification without changing the completed repair run', async () => {
    const pending: Incident = {
      ...demoIncident,
      source: 'live',
      status: 'repairing',
      certificate: null,
      coverage: { ...demoIncident.coverage, verifiedTargets: 9 },
    };
    const completed: Incident = { ...demoIncident, source: 'live' };
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ report: { status: 'verified' } })))
      .mockResolvedValueOnce(new Response(JSON.stringify(completed)));
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000002');
    render(<App initialIncident={pending} />);

    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry independent verification' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/repair-runs/${pending.runId}/verify`);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      requestId: '00000000-0000-4000-8000-000000000002',
    });
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/command-center/incidents/latest');
    expect(await screen.findByRole('button', { name: 'View certificate record' })).toBeVisible();
  });

  it('starts a normal Gmail conversation bound to the exact manifest task', async () => {
    const live: Incident = { ...demoIncident, source: 'live' };
    const route = {
      claimId: 'claim-scale-acquisition',
      claimStatement: 'The company should increase acquisition spend.',
      claimRisk: 'decision',
      artifactId: 'artifact-acquisition-task',
      taskId: 'task-42',
      taskListId: 'list-7',
    };
    const workflow = {
      workflowId: 'workflow-42',
      mailboxEmail: 'operator@example.com',
      authorizedSender: 'customer@example.com',
      packetId: live.packetId,
      claimId: route.claimId,
      artifactId: route.artifactId,
      taskId: route.taskId,
      taskListId: route.taskListId,
      status: 'active',
      createdAt: '2026-08-26T10:00:00Z',
      updatedAt: '2026-08-26T10:00:00Z',
    };
    const thread = {
      bindingId: 'binding-42',
      workflowId: workflow.workflowId,
      gmailThreadId: 'gmail-thread-42',
      bootstrapMessageId: 'gmail-message-42',
      subjectLine: 'Increase acquisition spend — customer update',
      source: 'company_started',
      createdAt: '2026-08-26T10:01:00Z',
      updatedAt: '2026-08-26T10:01:00Z',
    };
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            packetId: live.packetId,
            mailboxEmail: 'operator@example.com',
            routes: [route],
            workflows: [],
            threads: [],
            unmatchedRequests: [],
          }),
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              eventId: 'event-legacy-route',
              workflowId: 'workflow-42',
              gmailMessageId: 'gmail-message-legacy',
              gmailThreadId: 'gmail-thread-legacy',
              historyId: '101',
              sender: 'customer@example.com',
              recipient: 'operator@example.com',
              subjectLine: '[VX-ABCDEF123456] Update customer delivery',
              bodyHash: 'a'.repeat(64),
              proposedTitle: null,
              proposedNote: null,
              status: 'ignored',
              rationale: 'Historical test receipt.',
              riskFlags: [],
              taskRevision: null,
              receiptChecksum: 'b'.repeat(64),
              receivedAt: '2026-08-26T09:59:00Z',
              createdAt: '2026-08-26T10:00:00Z',
              updatedAt: '2026-08-26T10:00:00Z',
            },
          ]),
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ workflow, watch: {}, reused: false })))
      .mockResolvedValueOnce(new Response(JSON.stringify(thread)));
    render(<App initialIncident={live} />);

    fireEvent.click(screen.getByRole('button', { name: 'Email → Task' }));
    expect(await screen.findByDisplayValue('operator@example.com')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('customer@company.com'), {
      target: { value: 'customer@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Register customer & task' }));

    expect(
      await screen.findByRole('heading', { name: 'Start one normal customer conversation' }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Send opening email & bind thread' }));

    expect(await screen.findByText('Increase acquisition spend — customer update')).toBeVisible();
    expect(screen.getAllByText('Increase acquisition spend').length).toBeGreaterThan(0);
    expect(screen.getByText('Update customer delivery')).toBeVisible();
    expect(screen.queryByText(/VX-ABCDEF123456/)).not.toBeInTheDocument();
    expect(screen.getByText(/No routing code is visible or required/)).toBeVisible();
    expect(screen.getByRole('link', { name: 'Open company conversation ↗' })).toHaveAttribute(
      'href',
      expect.stringContaining('authuser=operator%40example.com'),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      packetId: live.packetId,
      claimId: route.claimId,
      artifactId: route.artifactId,
      authorizedSender: 'customer@example.com',
    });
    expect(fetchMock.mock.calls[3][0]).toBe(
      '/api/v1/email-task-workflows/workflow-42/conversation',
    );
  });

  it('lets an authenticated operator approve an escalated email into the exact task', async () => {
    const live: Incident = { ...demoIncident, source: 'live' };
    const route = {
      claimId: 'claim-scale-acquisition',
      claimStatement: 'The company should increase acquisition spend.',
      claimRisk: 'decision',
      artifactId: 'artifact-acquisition-task',
      taskId: 'task-42',
      taskListId: 'list-7',
    };
    const workflow = {
      workflowId: 'workflow-42',
      mailboxEmail: 'operator@example.com',
      authorizedSender: 'customer@example.com',
      packetId: live.packetId,
      claimId: route.claimId,
      artifactId: route.artifactId,
      taskId: route.taskId,
      taskListId: route.taskListId,
      status: 'active',
      createdAt: '2026-08-26T10:00:00Z',
      updatedAt: '2026-08-26T10:00:00Z',
    };
    const thread = {
      bindingId: 'binding-42',
      workflowId: workflow.workflowId,
      gmailThreadId: 'gmail-thread-42',
      bootstrapMessageId: 'gmail-message-42',
      subjectLine: 'Increase acquisition spend — customer update',
      source: 'company_started',
      createdAt: '2026-08-26T10:01:00Z',
      updatedAt: '2026-08-26T10:01:00Z',
    };
    const escalated = {
      eventId: 'email-event-42',
      workflowId: workflow.workflowId,
      gmailMessageId: 'customer-message-42',
      gmailThreadId: thread.gmailThreadId,
      historyId: '102',
      sender: 'customer@example.com',
      recipient: 'operator@example.com',
      subjectLine: 'Re: Increase acquisition spend — customer update',
      bodyHash: 'a'.repeat(64),
      proposedTitle: 'Decrease acquisition spend by 10%',
      proposedNote: 'Customer requested a 10% decrease from the quoted acquisition spend.',
      status: 'escalated',
      rationale: 'The customer reversed the current acquisition recommendation.',
      riskFlags: ['decision_reversal'],
      taskRevision: null,
      receiptChecksum: 'b'.repeat(64),
      reviewDecision: null,
      reviewRequestId: null,
      reviewReason: null,
      reviewedBy: null,
      reviewedAt: null,
      reviewReceiptChecksum: null,
      receivedAt: '2026-08-26T10:02:00Z',
      createdAt: '2026-08-26T10:02:00Z',
      updatedAt: '2026-08-26T10:02:00Z',
    };
    const applied = {
      ...escalated,
      status: 'applied',
      taskRevision: 'task-v2',
      reviewDecision: 'approve',
      reviewRequestId: '00000000-0000-4000-8000-000000000042',
      reviewReason:
        'Approved by the authenticated operator after reviewing the customer request and current task.',
      reviewedBy: 'operator@example.com',
      reviewedAt: '2026-08-26T10:03:00Z',
      reviewReceiptChecksum: 'c'.repeat(64),
    };
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000042');
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            packetId: live.packetId,
            mailboxEmail: 'operator@example.com',
            routes: [route],
            workflows: [workflow],
            threads: [thread],
            unmatchedRequests: [],
          }),
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify([escalated])))
      .mockResolvedValueOnce(new Response(JSON.stringify({ event: applied, reused: false })));
    render(<App initialIncident={live} />);

    fireEvent.click(screen.getByRole('button', { name: 'Email → Task' }));
    expect(
      (await screen.findAllByText('Decrease acquisition spend by 10%')).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/Proposed Google Task update/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Approve & update task' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls[2][0]).toBe('/api/v1/email-task-events/email-event-42/review');
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      requestId: '00000000-0000-4000-8000-000000000042',
      decision: 'approve',
      reason:
        'Approved by the authenticated operator after reviewing the customer request and current task.',
    });
    expect(await screen.findByText(/Approved by operator@example.com/)).toBeVisible();
    expect(screen.getByText('task-v2')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Approve & update task' })).not.toBeInTheDocument();
  });
});
