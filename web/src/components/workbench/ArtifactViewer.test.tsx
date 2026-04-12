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

  it('does not show the Diff tab when there are no previous version artifacts', () => {
    render(<ArtifactViewer />);
    expect(screen.queryByRole('button', { name: 'Diff' })).not.toBeInTheDocument();
  });

  it('shows version badge when iterationCount > 0', () => {
    useWorkbenchStore.setState({ iterationCount: 2 });
    render(<ArtifactViewer />);
    // Two artifacts => sub-navigation visible, each should have a "v3" badge
    expect(screen.getAllByText('v3').length).toBeGreaterThanOrEqual(1);
  });

  it('shows the Diff tab when previousVersionArtifacts and diffTargetVersion are set', () => {
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        {
          id: 'art-agent-old',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Old summary',
          preview: 'OLD PREVIEW',
          source: 'OLD SOURCE',
          language: 'markdown',
          created_at: '2026-04-10T00:00:00Z',
          version: 1,
        },
      ],
      diffTargetVersion: 1,
    });
    render(<ArtifactViewer />);
    expect(screen.getByRole('button', { name: 'Diff' })).toBeInTheDocument();
  });

  it('renders the diff view with added and removed lines', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        {
          id: 'art-agent-old',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Old summary',
          preview: 'line one\nold line',
          source: 'line one\nold line',
          language: 'python',
          created_at: '2026-04-10T00:00:00Z',
          version: 1,
        },
      ],
      diffTargetVersion: 1,
      artifacts: [
        {
          id: 'art-agent',
          task_id: 'task-role',
          category: 'agent',
          name: 'Agent role',
          summary: 'Agent summary',
          preview: 'line one\nnew line',
          source: 'line one\nnew line',
          language: 'python',
          created_at: '2026-04-11T00:00:00Z',
          version: 2,
        },
      ],
      activeArtifactId: 'art-agent',
    });
    render(<ArtifactViewer />);
    await user.click(screen.getByRole('button', { name: 'Diff' }));
    // The diff should show the removed old line and added new line
    expect(screen.getByText('old line')).toBeInTheDocument();
    expect(screen.getByText('new line')).toBeInTheDocument();
  });
});
