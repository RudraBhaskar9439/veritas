import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { demoIncident, type Incident } from './incident';

beforeEach(() => {
  window.localStorage.clear();
  window.scrollTo = vi.fn();
  vi.restoreAllMocks();
});

afterEach(cleanup);

describe('Veritas command center', () => {
  it('leads with the complete verified incident outcome', () => {
    render(<App initialIncident={demoIncident} />);

    expect(
      screen.getByRole('heading', { name: 'One number changed. Nine consequences repaired.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('13/13')).toBeInTheDocument();
    expect(screen.getByText('0', { selector: '.metric > strong' })).toBeInTheDocument();
    expect(
      screen.getByText(/All monitored claims in this Decision Packet are consistent/),
    ).toBeInTheDocument();
  });

  it('makes the registered blast radius legible in the opening view', () => {
    render(<App initialIncident={demoIncident} />);

    expect(
      screen.getByRole('heading', {
        name: 'The source moved. Veritas knew exactly what it owned.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('02 · 4 affected claims')).toBeInTheDocument();
    expect(screen.getByText('03 · 5 repaired artifacts')).toBeInTheDocument();
    expect(screen.getByText('0 inferred paths')).toBeInTheDocument();
  });

  it('shows an exact deterministic diff for every affected claim', () => {
    render(<App initialIncident={demoIncident} />);

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
              ],
            },
            checksum: 'a'.repeat(64),
            reused: false,
          }),
        ),
      );
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Generate real Workspace packet' }));
    expect(
      await screen.findByRole('heading', { name: 'Decision packet created and monitored.' }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/command-center/incidents/latest',
      '/api/v1/evidence/bootstrap',
      '/api/v1/packets',
    ]);
    expect(screen.getByRole('link', { name: /src-churn/ })).toHaveAttribute(
      'href',
      'https://docs.google.com/spreadsheets/d/real-sheet/edit',
    );
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
      );
    render(<App initialIncident={liveIncident} />);

    fireEvent.click(screen.getByRole('button', { name: 'New monitored packet' }));
    expect(
      await screen.findByRole('heading', { name: 'Decision packet created and monitored.' }),
    ).toBeInTheDocument();
    const bootstrapBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    const packetBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(bootstrapBody.requestId).toBe('generate-q3-executive-review-v1-123456781234-sources');
    expect(packetBody.blueprint.packetId).toBe('packet-q3-executive-review-123456781234');
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

    fireEvent.click(screen.getByRole('button', { name: 'Approve & continue' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0][0]).toContain(
      `/command-center/incidents/${pending.id}/runs/${pending.runId}/approvals/approval-1`,
    );
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/command-center/incidents/latest');
    expect(
      await screen.findByRole('heading', {
        name: 'One number changed. Nine consequences repaired.',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Decision-changing consequences need your approval')).toBeNull();
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

    fireEvent.click(screen.getByRole('button', { name: 'Retry independent verification' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/repair-runs/${pending.runId}/verify`);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      requestId: '00000000-0000-4000-8000-000000000002',
    });
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/command-center/incidents/latest');
    expect(await screen.findByRole('button', { name: 'View certificate record' })).toBeVisible();
  });
});
