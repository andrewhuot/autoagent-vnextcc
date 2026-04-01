import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Setup } from './Setup';

const apiMocks = vi.hoisted(() => ({
  useSetupOverview: vi.fn(),
  useSaveProviderKeys: vi.fn(),
  useSetRuntimeMode: vi.fn(),
  useTestProviderKey: vi.fn(),
}));

const toastMocks = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock('../lib/api', () => ({
  useSetupOverview: apiMocks.useSetupOverview,
  useSaveProviderKeys: apiMocks.useSaveProviderKeys,
  useSetRuntimeMode: apiMocks.useSetRuntimeMode,
  useTestProviderKey: apiMocks.useTestProviderKey,
}));

vi.mock('../lib/toast', () => ({
  toastError: toastMocks.toastError,
  toastSuccess: toastMocks.toastSuccess,
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/setup']}>
        <Setup />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const setupOverview = {
  workspace: {
    found: true,
    path: '/tmp/demo',
    label: 'Demo Workspace',
    runtime_config_path: '/tmp/demo/agentlab.yaml',
    active_config_version: 1,
  },
  doctor: {
    effective_mode: 'mock',
    preferred_mode: 'mock',
    mode_source: 'runtime config (agentlab.yaml)',
    message: 'Running in MOCK mode.',
    providers: [
      { provider: 'openai', model: 'gpt-4o', api_key_env: 'OPENAI_API_KEY', configured: false },
      { provider: 'anthropic', model: 'claude-sonnet-4-5', api_key_env: 'ANTHROPIC_API_KEY', configured: false },
      { provider: 'google', model: 'gemini-2.5-pro', api_key_env: 'GOOGLE_API_KEY', configured: false },
    ],
    api_keys: [
      { name: 'OPENAI_API_KEY', configured: false, masked_value: null, source: null },
      { name: 'ANTHROPIC_API_KEY', configured: false, masked_value: null, source: null },
      { name: 'GOOGLE_API_KEY', configured: false, masked_value: null, source: null },
    ],
    data_stores: [],
    issues: ['CLI is currently running in mock mode.'],
  },
  mcp_clients: [],
  recommended_commands: ['agentlab init'],
};

describe('Setup', () => {
  beforeEach(() => {
    apiMocks.useSetupOverview.mockReturnValue({
      data: setupOverview,
      isLoading: false,
      isError: false,
    });
    apiMocks.useSaveProviderKeys.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({ message: 'API keys saved.' }),
      isPending: false,
    });
    apiMocks.useTestProviderKey.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({ valid: true, message: 'Key valid.' }),
      isPending: false,
    });
    apiMocks.useSetRuntimeMode.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({
        preferred_mode: 'live',
        effective_mode: 'live',
        message: 'Running in LIVE mode — CLI will use configured real providers.',
      }),
      isPending: false,
    });
    toastMocks.toastError.mockReset();
    toastMocks.toastSuccess.mockReset();
  });

  it('tests and saves a Google API key, then switches to live mode', async () => {
    const user = userEvent.setup();
    const testKey = vi.fn().mockResolvedValue({ valid: true, message: 'Key valid.' });
    const saveKeys = vi.fn().mockResolvedValue({ message: 'API keys saved.' });
    const setMode = vi.fn().mockResolvedValue({
      preferred_mode: 'live',
      effective_mode: 'live',
      message: 'Running in LIVE mode — CLI will use configured real providers.',
    });

    apiMocks.useTestProviderKey.mockReturnValue({ mutateAsync: testKey, isPending: false });
    apiMocks.useSaveProviderKeys.mockReturnValue({ mutateAsync: saveKeys, isPending: false });
    apiMocks.useSetRuntimeMode.mockReturnValue({ mutateAsync: setMode, isPending: false });

    renderPage();

    await user.type(screen.getByLabelText('Google API Key'), 'AIza-test-key-123456');
    await user.click(screen.getByRole('button', { name: 'Save & Test Google API Key' }));

    await waitFor(() => {
      expect(testKey).toHaveBeenCalledWith({
        provider: 'google',
        api_key: 'AIza-test-key-123456',
      });
    });

    expect(saveKeys).toHaveBeenCalledWith({ google_api_key: 'AIza-test-key-123456' });
    expect(setMode).toHaveBeenCalledWith({ mode: 'live' });
    expect(screen.getByText('API key saved. Mode switched to live.')).toBeInTheDocument();
  });

  it('blocks switching to live mode when no API keys are configured', async () => {
    const user = userEvent.setup();
    const setMode = vi.fn();

    apiMocks.useSetRuntimeMode.mockReturnValue({ mutateAsync: setMode, isPending: false });
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Live mode' }));

    expect(setMode).not.toHaveBeenCalled();
    expect(screen.getByText('Add an API key above to enable live mode')).toBeInTheDocument();
  });
});
