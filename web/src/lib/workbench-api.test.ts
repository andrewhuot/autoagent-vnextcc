import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cancelWorkbenchRun } from './workbench-api';

describe('workbench-api hardening helpers', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts cancel requests to the server-side run cancel endpoint', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          project_id: 'wb-42',
          run_id: 'run-1',
          status: 'cancelled',
          run: { run_id: 'run-1', status: 'cancelled' },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await cancelWorkbenchRun('run-1', 'operator stopped it');

    expect(fetchMock).toHaveBeenCalledWith('/api/workbench/runs/run-1/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'operator stopped it' }),
    });
    expect(result.status).toBe('cancelled');
  });
});
