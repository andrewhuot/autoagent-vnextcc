import type React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBoundary } from './ErrorBoundary';

function BrokenComponent(): React.ReactElement {
  throw new Error('test crash');
}

function WorkingComponent() {
  return <p>All good</p>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <WorkingComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('All good')).toBeInTheDocument();
  });

  it('shows calm recovery UI when a child component throws', () => {
    // Suppress console.error from React's error boundary logging
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Something unexpected happened')).toBeInTheDocument();
    expect(screen.getByText(/Your work is safe/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try Again' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh Page' })).toBeInTheDocument();

    spy.mockRestore();
  });

  it('recovers when Try Again is clicked', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    let shouldThrow = true;

    function MaybeThrow() {
      if (shouldThrow) throw new Error('test crash');
      return <p>Recovered</p>;
    }

    render(
      <ErrorBoundary>
        <MaybeThrow />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something unexpected happened')).toBeInTheDocument();

    shouldThrow = false;
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Try Again' }));

    expect(screen.getByText('Recovered')).toBeInTheDocument();

    spy.mockRestore();
  });
});
