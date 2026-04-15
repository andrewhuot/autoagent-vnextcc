import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkbenchStore } from '../../lib/workbench-store';
import { ChatInput } from './ChatInput';

function renderInput(onSubmit = vi.fn(), onCancel = vi.fn()) {
  render(
    <div className="workbench-root">
      <ChatInput onSubmit={onSubmit} onCancel={onCancel} />
    </div>
  );
  return { onSubmit, onCancel };
}

describe('ChatInput', () => {
  beforeEach(() => {
    useWorkbenchStore.getState().reset();
  });

  it('treats reflecting as an in-flight state', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({ buildStatus: 'reflecting' });
    const { onSubmit, onCancel } = renderInput();

    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();

    await user.type(screen.getByLabelText('Build request'), 'Change the guardrail{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('treats presenting as an in-flight state', async () => {
    const user = userEvent.setup();
    useWorkbenchStore.setState({ buildStatus: 'presenting' });
    const { onSubmit } = renderInput();

    await user.type(screen.getByLabelText('Build request'), 'Ship it{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument();
  });
});
