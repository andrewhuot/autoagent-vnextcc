// Thin wrapper around builder API clients for Workbench page.
// Adds export and test-live endpoints (implemented by Track D).

async function fetchWorkbenchApi<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const fallback = 'Request failed. Please try again.';
    let message = fallback;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      message = payload.detail ?? payload.message ?? fallback;
    } catch {
      const text = await response.text().catch(() => '');
      message = text.trim() || fallback;
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export interface ExportAdkResult {
  filename: string;
  content: string;
  content_type: string;
  warnings: string[];
}

export interface ExportCxResult {
  filename: string;
  content: string;
  content_type: string;
  warnings: string[];
  diff: string | null;
}

export interface TestLiveResult {
  reply: string;
  trace_id: string;
  tool_calls: Array<Record<string, unknown>>;
}

export function exportAdk(sessionId: string): Promise<ExportAdkResult> {
  return fetchWorkbenchApi('/api/builder/export/adk', { session_id: sessionId });
}

export function exportCx(sessionId: string): Promise<ExportCxResult> {
  return fetchWorkbenchApi('/api/builder/export/cx', { session_id: sessionId });
}

export function testLive(sessionId: string, input: string): Promise<TestLiveResult> {
  return fetchWorkbenchApi('/api/builder/test-live', { session_id: sessionId, input });
}

// Re-export builder chat API functions for unified import surface.
export {
  sendBuilderMessage,
  getBuilderSession,
  previewBuilderSession,
} from './builder-chat-api';
