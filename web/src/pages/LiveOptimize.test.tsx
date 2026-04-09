import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LiveOptimize } from './LiveOptimize';

describe('LiveOptimize', () => {
  it('requires an agent when the live view is embedded inside the main optimize workflow', () => {
    render(<LiveOptimize requireSelectedAgent />);

    expect(screen.getByText('Simulation preview')).toBeInTheDocument();
    expect(screen.getAllByText('Select an agent above to start the live simulation.')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Start Optimization' })).toBeDisabled();
  });

  it('shows the selected agent context when an embedded live view has an active agent', () => {
    render(<LiveOptimize requireSelectedAgent activeAgentName="Order Guardian" />);

    expect(screen.getByText('Selected agent')).toBeInTheDocument();
    expect(screen.getByText('Order Guardian')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Optimization' })).toBeEnabled();
  });
});
