import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

beforeEach(() => {
  window.localStorage.clear();
  window.scrollTo = vi.fn();
});

afterEach(cleanup);

describe('Veritas command center', () => {
  it('leads with the complete verified incident outcome', () => {
    render(<App />);

    expect(
      screen.getByRole('heading', { name: 'Churn changed. The packet repaired itself.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('13/13')).toBeInTheDocument();
    expect(screen.getByText('0', { selector: '.metric > strong' })).toBeInTheDocument();
    expect(
      screen.getByText(/All monitored claims in this Decision Packet are consistent/),
    ).toBeInTheDocument();
  });

  it('shows an exact deterministic diff for every affected claim', () => {
    render(<App />);

    fireEvent.click(screen.getByRole('tab', { name: /Retention target/ }));
    expect(screen.getByText('The retention target has been achieved.')).toBeInTheDocument();
    expect(screen.getByText('The retention target has not been achieved.')).toBeInTheDocument();
    expect(screen.getByText('churn_lte_target_5_percent@1')).toBeInTheDocument();
  });

  it('recovers the selected command-center view after a refresh', () => {
    const first = render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Blast radius' }));
    expect(
      screen.getByRole('heading', { name: 'One cell changed. These are the exact consequences.' }),
    ).toBeInTheDocument();
    first.unmount();

    render(<App />);
    expect(
      screen.getByRole('heading', { name: 'One cell changed. These are the exact consequences.' }),
    ).toBeInTheDocument();
  });

  it('exposes the independent checks and immutable evidence set', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Verification' }));

    expect(
      screen.getByRole('heading', { name: 'The repair agent does not grade its own work.' }),
    ).toBeInTheDocument();
    expect(screen.getByText('36 checks passed')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Evidence versions' })).toBeInTheDocument();
    expect(screen.getByText('Metrics!B17')).toBeInTheDocument();
  });

  it('can replay the incident through an announced live region', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Replay incident' }));

    expect(screen.getByRole('status')).toHaveTextContent('Incident replay step 1 of 6');
    expect(screen.getByRole('button', { name: 'Replaying incident' })).toBeInTheDocument();
  });
});
