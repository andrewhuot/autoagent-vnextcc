import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IterationControls } from './IterationControls';
import { useWorkbenchStore } from '../../lib/workbench-store';

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
    // Simulate a completed build — set buildStatus directly since
    // build.completed keeps status as 'running' until run.completed.
    useWorkbenchStore.setState({ buildStatus: 'done', version: 1 });
    renderControls();
    expect(screen.getByTestId('iteration-controls')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /iterate/i })).toBeInTheDocument();
  });

  it('opens the inline input when Iterate is clicked', async () => {
    useWorkbenchStore.setState({ buildStatus: 'done', version: 1 });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    expect(screen.getByLabelText('Iteration message')).toBeInTheDocument();
  });

  it('calls onIterate with the typed message when Run is clicked', async () => {
    const handler = vi.fn();
    useWorkbenchStore.setState({ buildStatus: 'done', version: 1 });
    const user = userEvent.setup();
    renderControls(handler);
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    await user.type(screen.getByLabelText('Iteration message'), 'Add retry logic');
    await user.click(screen.getByRole('button', { name: /^run$/i }));
    expect(handler).toHaveBeenCalledOnce();
    expect(handler).toHaveBeenCalledWith('Add retry logic');
  });

  it('dismisses the inline input when Cancel is clicked', async () => {
    useWorkbenchStore.setState({ buildStatus: 'done', version: 1 });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /iterate/i }));
    expect(screen.getByLabelText('Iteration message')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(screen.queryByLabelText('Iteration message')).toBeNull();
  });

  it('shows iteration history list when there are previous iterations', async () => {
    useWorkbenchStore.getState().startIteration('First change');
    // After startIteration, status is 'starting'. Set to 'done' to render controls.
    useWorkbenchStore.setState({ buildStatus: 'done', version: 2 });
    const user = userEvent.setup();
    renderControls();
    // History toggle should appear with count.
    const toggle = screen.getByText(/iteration/);
    await user.click(toggle);
    expect(screen.getByLabelText('Iteration history')).toBeInTheDocument();
    expect(screen.getByText('First change')).toBeInTheDocument();
  });

  it('shows the diff compare button when version > 1', () => {
    useWorkbenchStore.setState({ buildStatus: 'done', version: 2 });
    renderControls();
    expect(screen.getByRole('button', { name: /compare with v/i })).toBeInTheDocument();
  });

  it('activates diff mode and shows the version as active', async () => {
    useWorkbenchStore.setState({ buildStatus: 'done', version: 2 });
    const user = userEvent.setup();
    renderControls();
    await user.click(screen.getByRole('button', { name: /compare with v/i }));
    // After activating, the button label should change to show active state.
    expect(screen.getByRole('button', { name: /comparing v/i })).toBeInTheDocument();
    // Store should reflect the diff target.
    expect(useWorkbenchStore.getState().diffTargetVersion).toBe(1);
  });

  it('deactivates diff when the comparing button is clicked again', async () => {
    useWorkbenchStore.setState({ buildStatus: 'done', version: 2 });
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
