import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Build } from './Build';

function renderPage(initialEntry = '/build') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Build />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Build', () => {
  beforeEach(() => {
    const storage = new Map<string, string>();
    const localStorageMock = {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storage.set(key, value);
      }),
      removeItem: vi.fn((key: string) => {
        storage.delete(key);
      }),
      clear: vi.fn(() => {
        storage.clear();
      }),
    };

    vi.stubGlobal('fetch', vi.fn());
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
  });

  it('shows the unified tab shell and defaults to the prompt workspace', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Build' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Prompt' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Transcript' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Builder Chat' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Saved Artifacts' })).toBeInTheDocument();
    expect(screen.getByLabelText('Agent description')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'XML Instruction Studio' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Raw XML' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('XML instruction editor')).toBeInTheDocument();
  });

  it('switches to the builder chat workspace without losing the builder controls', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('tab', { name: 'Builder Chat' }));

    expect(screen.getByText('Conversational Builder')).toBeInTheDocument();
    expect(screen.getByTestId('builder-composer')).toBeInTheDocument();
    expect(screen.getByText('Download Config')).toBeInTheDocument();
    expect(screen.getByText('Run Eval')).toBeInTheDocument();
  });

  it('opens a deep-linked build tab from the route query string', () => {
    renderPage('/build?tab=transcript');

    expect(screen.getByRole('tab', { name: 'Transcript' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Start from Transcripts')).toBeInTheDocument();
  });

  it('lists persisted build artifacts in the saved artifacts tab', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      'autoagent.build-artifacts.v1',
      JSON.stringify([
        {
          artifact_id: 'artifact-123',
          title: 'Airline Support Agent',
          summary: 'Generated from a prompt',
          source: 'prompt',
          status: 'complete',
          created_at: '2026-03-29T12:00:00.000Z',
          updated_at: '2026-03-29T12:00:00.000Z',
          config_yaml: 'agent_name: Airline Support Agent',
        },
      ])
    );

    renderPage();

    await user.click(screen.getByRole('tab', { name: 'Saved Artifacts' }));

    expect(screen.getByRole('heading', { name: 'Saved Artifacts' })).toBeInTheDocument();
    expect(screen.getByText('Airline Support Agent')).toBeInTheDocument();
    expect(screen.getByText('Generated from a prompt')).toBeInTheDocument();
  });

  it('switches the XML instruction studio into form mode', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Form View' }));

    expect(screen.getByRole('button', { name: 'Form View' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Instruction role')).toBeInTheDocument();
    expect(screen.getByLabelText('Primary goal')).toBeInTheDocument();
  });

  it('shows inline XML validation feedback when the raw editor becomes malformed', async () => {
    const user = userEvent.setup();
    renderPage();

    const editor = screen.getByLabelText('XML instruction editor');
    await user.clear(editor);
    await user.type(editor, '<role>Broken</role><persona>');

    expect(screen.getByText(/XML parse error/i)).toBeInTheDocument();
  });

  it('can insert a guide example into the XML editor from the examples library', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Weather Routing Guide' }));

    const editor = screen.getByLabelText('XML instruction editor') as HTMLTextAreaElement;
    expect(editor.value).toContain('<role>The main Weather Agent coordinating multiple agents.</role>');
    expect(editor.value).toContain('Begin example');
  });
});
