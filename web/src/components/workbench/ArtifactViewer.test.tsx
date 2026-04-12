import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { ArtifactViewer } from './ArtifactViewer';

describe('ArtifactViewer', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
    useWorkbenchStore.getState().hydrate({
      projectId: 'wb-filter',
      projectName: 'Filter Workbench',
      target: 'portable',
      environment: 'draft',
      version: 1,
      artifacts: [
        {
          id: 'art-agent',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Agent summary',
          preview: 'AGENT PREVIEW',
          source: 'AGENT SOURCE',
          language: 'markdown',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
        {
          id: 'art-tool',
          task_id: 'task-tool',
          category: 'tool',
          name: 'flight_status_lookup.py',
          summary: 'Tool summary',
          preview: 'TOOL PREVIEW',
          source: 'TOOL SOURCE',
          language: 'python',
          created_at: '2026-04-11T00:00:00Z',
          version: 1,
        },
      ],
    });
    useWorkbenchStore.getState().setActiveArtifact('art-agent');
  });

  it('switches the active artifact to the selected category', async () => {
    const user = userEvent.setup();
    render(<ArtifactViewer />);

    expect(screen.getByText('AGENT PREVIEW')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Tools/ }));

    expect(screen.getByText('flight_status_lookup.py')).toBeInTheDocument();
    expect(screen.queryByText('AGENT PREVIEW')).not.toBeInTheDocument();
  });
});
