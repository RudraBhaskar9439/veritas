import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { App } from './App';

afterEach(cleanup);

describe('App', () => {
  it('communicates the Veritas product invariant', () => {
    render(<App />);

    expect(
      screen.getByRole('heading', { name: 'AI created the work. Veritas keeps it true.' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'No certificate without complete verification.' }),
    ).toBeInTheDocument();
  });

  it('shows each foundation boundary', () => {
    render(<App />);

    expect(screen.getByText('Claim Manifest')).toBeInTheDocument();
    expect(screen.getByText('Runtime services')).toBeInTheDocument();
    expect(screen.getByText('Google Cloud foundation')).toBeInTheDocument();
  });
});
