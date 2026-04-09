import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastViewport } from './ToastViewport';
import { toastSuccess, useToastStore } from '../lib/toast';

describe('ToastViewport', () => {
  afterEach(() => {
    useToastStore.getState().clearToasts();
  });

  it('renders toast actions and invokes them before dismissing the toast', async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();

    render(<ToastViewport />);

    toastSuccess('Saved to workspace', '/tmp/workspace/configs/v002.yaml', {
      action: {
        label: 'Run Eval',
        onClick: onAction,
      },
    });

    expect(await screen.findByRole('status')).toHaveTextContent('Saved to workspace');

    await user.click(screen.getByRole('button', { name: 'Run Eval' }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Saved to workspace')).not.toBeInTheDocument();
  });
});
