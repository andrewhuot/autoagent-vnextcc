import { render, screen } from '@testing-library/react';
import { Rocket } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { EmptyState } from './EmptyState';

describe('EmptyState', () => {
  it('explains state type, why no data exists, and the next operator action', () => {
    render(
      <EmptyState
        icon={Rocket}
        state="no-data"
        title="No deployment history"
        description="Deployment events will appear after a version is rolled out."
        nextAction="Deploy a canary or refresh after a rollout starts."
      />
    );

    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'No deployment history' })).toBeInTheDocument();
    expect(screen.getByText('Deployment events will appear after a version is rolled out.')).toBeInTheDocument();
    expect(screen.getByText('Next: Deploy a canary or refresh after a rollout starts.')).toBeInTheDocument();
  });
});
