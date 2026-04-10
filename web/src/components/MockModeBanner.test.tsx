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

  it('shows an Open Setup link when the app reports mock mode', async () => {
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
    expect(screen.getByText('Preview mode is on')).toBeInTheDocument();
    expect(
      screen.getByText('AgentLab is using simulated responses until live providers are ready.')
    ).toBeInTheDocument();

    const exitLink = screen.getByRole('link', { name: 'Open Setup' });
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

  it('renders on the /build route so users see mock mode warnings while building', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          mock_mode: true,
          mock_reasons: ['Mock mode explicitly enabled.'],
          real_provider_configured: false,
        }),
      })
    );

    renderBanner('/build');

    expect(await screen.findByRole('alert')).toBeInTheDocument();
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

  it('shows a frontend-only banner when the backend health endpoint is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('backend offline')));

    renderBanner('/build');

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Frontend-only mode')).toBeInTheDocument();
    expect(
      screen.getByText('AgentLab cannot reach the backend right now, so live status and saved actions may be unavailable.')
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry connection' })).toBeInTheDocument();
  });

  it('transitions from frontend-only to hidden when retry succeeds', async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          mock_mode: false,
          mock_reasons: [],
          real_provider_configured: true,
        }),
      });

    vi.stubGlobal('fetch', fetchMock);

    renderBanner('/build');

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Frontend-only mode')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry connection' }));

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
