import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ArtifactViewer } from './ArtifactViewer';
import { useWorkbenchStore } from '../../lib/workbench-store';
import type { WorkbenchArtifact } from '../../lib/workbench-api';

function makeArtifact(overrides: Partial<WorkbenchArtifact> = {}): WorkbenchArtifact {
  return {
    id: 'art-1',
    task_id: 'task-root',
    category: 'agent',
    name: 'My Agent',
    summary: 'An agent',
    preview: 'def run():\n    return 1',
    source: 'def run():\n    return 1',
    language: 'python',
    created_at: '2026-04-11T00:00:00Z',
    version: 1,
    ...overrides,
  };
}

function renderViewer() {
  return render(
    <div className="workbench-root">
      <ArtifactViewer />
    </div>
  );
}

describe('ArtifactViewer', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('shows the empty state when no artifacts exist and build is idle', () => {
    renderViewer();
    expect(
      screen.getByText('Processes paused, click to wake up')
    ).toBeInTheDocument();
  });

  it('shows a generating message when build is running with no artifacts', () => {
    useWorkbenchStore.getState().beginBuild('Build something');
    renderViewer();
    expect(screen.getByText('Generating artifacts...')).toBeInTheDocument();
  });

  it('renders artifact name in the sub-navigation when multiple artifacts exist', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: { task_id: 'task-root', artifact: makeArtifact({ id: 'a1', name: 'Alpha Agent' }) },
    });
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: { task_id: 'task-root', artifact: makeArtifact({ id: 'a2', name: 'Beta Tool' }) },
    });
    renderViewer();
    expect(screen.getByRole('button', { name: /alpha agent/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /beta tool/i })).toBeInTheDocument();
  });

  it('shows a version badge when artifact.version > 1', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: { task_id: 'task-root', artifact: makeArtifact({ id: 'a1', name: 'Alpha' }) },
    });
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: {
        task_id: 'task-root',
        artifact: makeArtifact({ id: 'a2', name: 'Beta', version: 2 }),
      },
    });
    renderViewer();
    // v2 badge should appear for the second artifact.
    expect(screen.getByText('v2')).toBeInTheDocument();
  });

  it('switches to Source tab when Source button is clicked', async () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: { task_id: 'task-root', artifact: makeArtifact() },
    });
    const user = userEvent.setup();
    renderViewer();
    await user.click(screen.getByRole('button', { name: 'Source' }));
    expect(useWorkbenchStore.getState().activeArtifactView).toBe('source');
  });

  it('does not show the Diff tab when there are no previous version artifacts', () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: { task_id: 'task-root', artifact: makeArtifact() },
    });
    renderViewer();
    // Diff tab only appears when diff data exists in the store.
    expect(screen.queryByRole('button', { name: /diff/i })).toBeNull();
  });

  it('shows the Diff tab when previousVersionArtifacts and diffTargetVersion are set', () => {
    // Inject a previous artifact snapshot and activate diff mode.
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        makeArtifact({ source: 'def run():\n    return 0', preview: 'def run():\n    return 0' }),
      ],
      diffTargetVersion: 1,
    });
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: {
        task_id: 'task-root',
        artifact: makeArtifact({ source: 'def run():\n    return 1', preview: 'def run():\n    return 1' }),
      },
    });
    renderViewer();
    expect(screen.getByRole('button', { name: /diff v1/i })).toBeInTheDocument();
  });

  it('renders the diff view with added and removed lines', async () => {
    useWorkbenchStore.setState({
      previousVersionArtifacts: [
        makeArtifact({ source: 'def run():\n    return 0', preview: 'def run():\n    return 0' }),
      ],
      diffTargetVersion: 1,
    });
    useWorkbenchStore.getState().dispatchEvent({
      event: 'artifact.updated',
      data: {
        task_id: 'task-root',
        artifact: makeArtifact({ source: 'def run():\n    return 1', preview: 'def run():\n    return 1' }),
      },
    });
    const user = userEvent.setup();
    renderViewer();
    await user.click(screen.getByRole('button', { name: /diff v1/i }));
    // The diff view should show the changed lines count.
    expect(screen.getByText(/changed line/)).toBeInTheDocument();
  });
});
