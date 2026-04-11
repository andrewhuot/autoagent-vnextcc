import { useState } from 'react';
import { testLive } from '../../../lib/workbench-api';

interface LiveResponse {
  reply: string;
  trace_id: string;
  tool_calls: Array<Record<string, unknown>>;
}

interface TestLiveTabProps {
  sessionId: string | null;
}

const MAX_RESPONSES = 5;

export function TestLiveTab({ sessionId }: TestLiveTabProps) {
  const [input, setInput] = useState('');
  const [responses, setResponses] = useState<LiveResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!sessionId) {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
        Start a conversation to enable live testing.
      </p>
    );
  }

  const handleSend = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    const sentInput = input.trim();
    setInput('');
    try {
      const res = await testLive(sessionId, sentInput);
      setResponses((prev) => [res as LiveResponse, ...prev].slice(0, MAX_RESPONSES));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test failed');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      void handleSend();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Send a message… (Enter to send)"
          disabled={loading}
          className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={loading || !input.trim()}
          className="rounded-md bg-sky-700 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? '…' : 'Send'}
        </button>
      </div>

      {error ? (
        <p className="rounded-md border border-red-800 bg-red-950/50 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      ) : null}

      {responses.length === 0 && !loading ? (
        <p className="rounded-md border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-500">
          No responses yet.
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        {responses.map((resp, idx) => (
          <div
            key={`${resp.trace_id}-${idx}`}
            className="rounded-md border border-slate-700 bg-slate-900/70 p-3"
          >
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Response
              </p>
              <span className="font-mono text-[10px] text-slate-600">{resp.trace_id}</span>
            </div>
            <p className="whitespace-pre-wrap text-xs text-slate-200">{resp.reply}</p>
            {resp.tool_calls && resp.tool_calls.length > 0 ? (
              <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] text-slate-400">
                {JSON.stringify(resp.tool_calls, null, 2)}
              </pre>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
