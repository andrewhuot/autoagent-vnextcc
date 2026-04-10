import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getBuilderSession,
  sendBuilderMessage,
} from './builder-chat-api';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: init?.status ?? 200,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
}

describe('builder chat api', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  it('extracts API detail messages from failed builder session restores', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Builder session not found' }, { status: 404 }))
    );

    await expect(getBuilderSession('missing-session')).rejects.toMatchObject({
      message: 'Builder session not found',
      status: 404,
    });
  });

  it('falls back to a human-friendly rate limit message for builder chat failures', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 429 }))
    );

    await expect(sendBuilderMessage({ message: 'Improve escalation handling.' })).rejects.toMatchObject({
      message: 'Rate limited — wait a moment, then try again.',
      status: 429,
    });
  });
});
