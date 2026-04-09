import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WebSocketClient } from './websocket';

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  receive(message: unknown): void {
    const data = typeof message === 'string' ? message : JSON.stringify(message);
    this.onmessage?.({ data });
  }

  static latest(): MockWebSocket {
    const socket = MockWebSocket.instances.at(-1);
    if (!socket) {
      throw new Error('No mock WebSocket instance was created');
    }
    return socket;
  }
}

describe('WebSocketClient', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('dispatches flat backend messages to type handlers', () => {
    const client = new WebSocketClient('/ws');
    const handler = vi.fn();

    client.onMessage('eval_complete', handler);
    client.connect();

    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({
      type: 'eval_complete',
      task_id: 'run-12345678',
      composite: 0.6907,
      passed: 8,
      total: 31,
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: 'run-12345678',
        composite: 0.6907,
        passed: 8,
        total: 31,
      })
    );
  });

  it('keeps supporting payload-enveloped messages', () => {
    const client = new WebSocketClient('/ws');
    const handler = vi.fn();

    client.onMessage('eval_complete', handler);
    client.connect();

    const socket = MockWebSocket.latest();
    socket.open();
    socket.receive({
      type: 'eval_complete',
      payload: {
        task_id: 'run-87654321',
        composite: 0.75,
      },
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        task_id: 'run-87654321',
        composite: 0.75,
      })
    );
  });
});
