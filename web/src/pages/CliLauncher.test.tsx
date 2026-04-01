import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { CliLauncher } from './CliLauncher';

describe('CliLauncher', () => {
  it('renders quick start and the common command grid', () => {
    render(
      <MemoryRouter initialEntries={['/cli']}>
        <CliLauncher />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'Launch the CLI' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Quick Start' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Common Commands' })).toBeInTheDocument();
    expect(screen.getByText('npx agentlab')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'agentlab optimize' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'agentlab help' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy quick start command' })).toBeInTheDocument();
  });
});
