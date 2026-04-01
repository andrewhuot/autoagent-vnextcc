import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { Docs } from './Docs';

describe('Docs', () => {
  it('renders CLI and web UI guide sections', () => {
    render(
      <MemoryRouter initialEntries={['/docs']}>
        <Docs />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: 'Documentation' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Using the CLI' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Using the Web UI' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Getting Started' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Dashboard Overview' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Need Help?' })).toBeInTheDocument();
  });
});
