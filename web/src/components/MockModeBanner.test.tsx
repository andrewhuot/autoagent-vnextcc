import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MockModeBanner } from './MockModeBanner';

function renderBanner(initialEntry = '/evals') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <MockModeBanner />
    </MemoryRouter>
  );
}

describe('MockModeBanner', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows an Exit Mock Mode link to setup when the app reports mock mode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: true,
          mock_reasons: ['Mock mode explicitly enabled by optimizer.use_mock.'],
          real_provider_configured: false,
        }),
      })
    );

    renderBanner();

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Running in mock mode — add API keys for live optimization')).toBeInTheDocument();

    const exitLink = screen.getByRole('link', { name: 'Exit Mock Mode' });
    expect(exitLink).toHaveAttribute('href', '/setup');
  });

  it('shows dismiss button only when real_provider_configured is true', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: true,
          mock_reasons: ['Mock mode explicitly enabled by optimizer.use_mock.'],
          real_provider_configured: true,
        }),
      })
    );

    renderBanner();

    const dismissButton = await screen.findByRole('button', { name: 'Dismiss mock mode warning' });
    expect(dismissButton).toBeInTheDocument();
  });

  it('does not show dismiss button when real_provider_configured is false', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: true,
          mock_reasons: ['Mock mode explicitly enabled by optimizer.use_mock.'],
          real_provider_configured: false,
        }),
      })
    );

    renderBanner();

    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Dismiss mock mode warning' })).not.toBeInTheDocument();
  });

  it('hides the banner when dismiss is clicked', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: true,
          mock_reasons: [],
          real_provider_configured: true,
        }),
      })
    );

    const user = userEvent.setup();
    renderBanner();

    const dismissButton = await screen.findByRole('button', { name: 'Dismiss mock mode warning' });
    await user.click(dismissButton);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not render when the health endpoint reports live mode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: false,
          mock_reasons: [],
          real_provider_configured: true,
        }),
      })
    );

    renderBanner();

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
