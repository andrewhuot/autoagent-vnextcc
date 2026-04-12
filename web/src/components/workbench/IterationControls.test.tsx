import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IterationControls } from './IterationControls';
import { useWorkbenchStore } from '../../lib/workbench-store';
import type { WorkbenchArtifact } from '../../lib/workbench-api';

function makeArtifact(id = 'art-1'): WorkbenchArtifact {
  return {
    id,
    task_id: 'task-root',
    category: 'agent',
    name: 'Agent',
    summary: 'An agent',
    preview: 'print("hello")',
    source: 'print("hello")',
    language: 'python',
    created_at: '2026-04-11T00:00:00Z',
    version: 1,
  };
}

function renderControls(onIterate = vi.fn()) {
  return render(
    <div className="workbench-root">
      <IterationControls onIterate={onIterate} />
    </div>
  );
}

describe('IterationControls', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('renders nothing when idle with no prior work', () => {
    renderControls();
    expect(screen.queryByTestId('iteration-controls')).toBeNull();
  });

  it('renders when build is done', () => {
    // Simulate a completed build.
    useWorkbenchStore.getState().dispatchEvent({
      event: 'plan.ready',
      data: {
        project_id: 'wb-1',
        plan: {
          id: 'r', title: 'Root', status: 'pending', description: '', children: [],
          artifact_ids: [], log: [], parent_id: null, started_at: null, completed_at: null,
        },
      },
    });
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 1 },
    });
    renderControls();
    expect(screen.getByTestId('iteration-controls')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /iterate/i })).toBeInTheDocument();
  });

  it('opens the inline input when Iterate is clicked', async () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 1 },
    });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    expect(screen.getByLabelText('Iteration message')).toBeInTheDocument();
  });

  it('calls onIterate with the typed message when Run is clicked', async () => {
    const handler = vi.fn();
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 1 },
    });
    const user = userEvent.setup();
    renderControls(handler);
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    await user.type(screen.getByLabelText('Iteration message'), 'Add retry logic');
    await user.click(screen.getByRole('button', { name: /^run$/i }));
    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith('Add retry logic');
  });

  it('dismisses the inline input when Cancel is clicked', async () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 1 },
    });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    expect(screen.getByLabelText('Iteration message')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.queryByLabelText('Iteration message')).toBeNull();
  });

  it('shows iteration history list when there are previous iterations', async () => {
    useWorkbenchStore.getState().startIteration('First change');
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 2 },
    });
    const user = userEvent.setup();
    renderControls();
    // History toggle should appear with count.
    const toggle = screen.getByText(/iteration/);
    await user.click(toggle);
    expect(screen.getByLabelText('Iteration history')).toBeInTheDocument();
    expect(screen.getByText('First change')).toBeInTheDocument();
  });

  it('shows the diff compare button when version > 1', () => {
    // Set version to 2 via a build.completed event.
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 2 },
    });
    renderControls();
    expect(screen.getByRole('button', { name: /compare with v/i })).toBeInTheDocument();
  });

  it('activates diff mode and shows the version as active', async () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 2 },
    });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /compare with v/i }));
    // After activating, the button label should change to show active state.
    expect(screen.getByRole('button', { name: /comparing v/i })).toBeInTheDocument();
    // Store should reflect the diff target.
    expect(useWorkbenchStore.getState().diffTargetVersion).toBe(1);
  });

  it('deactivates diff when the comparing button is clicked again', async () => {
    useWorkbenchStore.getState().dispatchEvent({
      event: 'build.completed',
      data: { project_id: 'wb-1', version: 2 },
    });
    const user = userEvent.setup();
    renderControls();
    // Activate.
    await user.click(screen.getByRole('button', { name: /compare with v/i }));
    expect(useWorkbenchStore.getState().diffTargetVersion).toBe(1);
    // Deactivate.
    await user.click(screen.getByRole('button', { name: /comparing v/i }));
    expect(useWorkbenchStore.getState().diffTargetVersion).toBeNull();
  });
});
