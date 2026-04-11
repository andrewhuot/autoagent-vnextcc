import { useState } from 'react';
import type { BuildPreviewResult } from '../../../lib/types';
import { previewBuilderSession } from '../../../lib/workbench-api';

interface PreviewTabProps {
  sessionId: string | null;
}

export function PreviewTab({ sessionId }: PreviewTabProps) {
  const [input, setInput] = useState('');
  const [result, setResult] = useState<BuildPreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!sessionId) {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
        Start a conversation to enable preview.
      </p>
    );
  }

  const handleRun = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await previewBuilderSession({ session_id: sessionId, message: input.trim() });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      void handleRun();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder="Enter a test message… (Cmd+Enter to run)"
          className="w-full resize-none rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500"
        />
        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={loading || !input.trim()}
          className="self-end rounded-md bg-sky-700 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Running…' : 'Run'}
        </button>
      </div>

      {error ? (
        <p className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      ) : null}

      {result ? (
        <div className="flex flex-col gap-2">
          {result.mock_mode ? (
            <p className="rounded-md border border-yellow-800 bg-yellow-950/50 px-3 py-1.5 text-[11px] text-yellow-400">
              Mock mode — responses are simulated.
            </p>
          ) : null}

          <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Response
            </p>
            <p className="whitespace-pre-wrap text-xs text-slate-200">{result.response}</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-400">
              {result.latency_ms}ms
            </span>
            <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-400">
              {result.token_count} tokens
            </span>
            {result.specialist_used ? (
              <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-400">
                {result.specialist_used}
              </span>
            ) : null}
          </div>

          {result.tool_calls.length > 0 ? (
            <div className="rounded-md border border-slate-700 bg-slate-900/70 p-3">
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Tool Calls
              </p>
              <pre className="whitespace-pre-wrap font-mono text-[11px] text-slate-300">
                {JSON.stringify(result.tool_calls, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
