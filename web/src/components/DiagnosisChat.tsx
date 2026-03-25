import { useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, Send, Sparkles, X } from 'lucide-react';
import { toastError, toastSuccess } from '../lib/toast';
import type { ChatMessage } from '../lib/types';

interface DiagnoseChatResponse {
  response: string;
  actions?: Array<{ label: string; action: string }>;
  clusters?: Array<{ index: number; bucket: string; count: number; focused: boolean }>;
  session_id: string;
}

function makeMessage(
  role: 'user' | 'assistant',
  content: string,
  metadata?: ChatMessage['metadata'],
): ChatMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content,
    timestamp: Date.now(),
    metadata,
  };
}

function parseAssistantMetadata(
  content: string,
  actions: Array<{ label: string; action: string }> | undefined,
): ChatMessage['metadata'] {
  const metadata: ChatMessage['metadata'] = {
    type: 'text',
    actions: actions || [],
  };

  const diffMarker = '\nDiff:\n';
  if (content.includes(diffMarker)) {
    metadata.type = 'diff';
    metadata.diff = content.split(diffMarker).slice(1).join(diffMarker).trim();
  }

  const evalMatch = content.match(/([0-9]+\.[0-9]+)\s*->\s*([0-9]+\.[0-9]+)/);
  if (evalMatch) {
    metadata.metrics = {
      before: Number(evalMatch[1]),
      after: Number(evalMatch[2]),
    };
    if (metadata.type !== 'diff') {
      metadata.type = 'metrics';
    }
  }

  return metadata;
}

export function DiagnosisChat() {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string>('');
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const initializedRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function callDiagnose(message: string) {
    const payload: Record<string, string> = { message };
    if (sessionId) payload.session_id = sessionId;

    const res = await fetch('/api/diagnose/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Diagnosis API failed with ${res.status}`);
    }
    const data = (await res.json()) as DiagnoseChatResponse;
    setSessionId(data.session_id);

    const assistantMetadata = parseAssistantMetadata(data.response, data.actions);
    setMessages((prev) => [...prev, makeMessage('assistant', data.response, assistantMetadata)]);

    const applyMatch = data.response.match(/Score change:\s*([0-9.]+)\s*->\s*([0-9.]+)/i);
    if (applyMatch) {
      const before = Number(applyMatch[1]);
      const after = Number(applyMatch[2]);
      toastSuccess(
        'Fix applied',
        `Composite score improved by ${(after - before).toFixed(4)} (${before.toFixed(4)} -> ${after.toFixed(4)}).`,
      );
    }
  }

  async function initializeSessionIfNeeded() {
    if (initializedRef.current) return;
    initializedRef.current = true;
    setLoading(true);
    try {
      await callDiagnose('');
    } catch (err) {
      initializedRef.current = false;
      toastError('Could not start diagnosis chat', err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) {
      void initializeSessionIfNeeded();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function sendUserMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || loading) return;

    setMessages((prev) => [...prev, makeMessage('user', trimmed)]);
    setInput('');
    setLoading(true);
    try {
      await callDiagnose(trimmed);
    } catch (err) {
      toastError('Diagnosis request failed', err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const lastAssistantActions = useMemo(() => {
    const reversed = [...messages].reverse();
    for (const msg of reversed) {
      if (msg.role === 'assistant' && msg.metadata?.actions && msg.metadata.actions.length > 0) {
        return msg.metadata.actions;
      }
    }
    return [];
  }, [messages]);

  return (
    <div className="fixed bottom-5 right-5 z-40">
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="group flex items-center gap-2 rounded-full border border-sky-200 bg-white px-4 py-2.5 text-sm font-semibold text-sky-700 shadow-lg shadow-sky-100 transition hover:-translate-y-0.5 hover:bg-sky-50"
          type="button"
        >
          <MessageSquare className="h-4 w-4 text-sky-600" />
          Diagnose Agent
          <Sparkles className="h-3.5 w-3.5 text-amber-500 transition group-hover:rotate-12" />
        </button>
      )}

      {open && (
        <div className="flex h-[min(78vh,640px)] w-[min(92vw,390px)] flex-col overflow-hidden rounded-2xl border border-sky-100 bg-white shadow-2xl shadow-sky-100">
          <div className="flex items-center justify-between border-b border-sky-100 bg-gradient-to-r from-sky-50 to-cyan-50 px-4 py-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Diagnosis Chat</h3>
              <p className="text-xs text-slate-500">Conversational failure triage + guided fixes</p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="rounded-md p-1.5 text-slate-500 transition hover:bg-white hover:text-slate-700"
              type="button"
              aria-label="Close diagnosis chat"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto bg-slate-50/60 p-3">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={
                    msg.role === 'user'
                      ? 'max-w-[86%] rounded-2xl rounded-tr-sm bg-sky-600 px-3 py-2 text-sm text-white'
                      : 'max-w-[86%] rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700'
                  }
                >
                  <p className="whitespace-pre-wrap">{msg.content}</p>

                  {msg.metadata?.metrics && (
                    <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-700">
                      Score: {msg.metadata.metrics.before.toFixed(4)} {'->'} {msg.metadata.metrics.after.toFixed(4)}
                    </div>
                  )}

                  {msg.metadata?.diff && (
                    <pre className="mt-2 overflow-x-auto rounded-lg border border-slate-200 bg-slate-900/95 p-2 text-[11px] text-slate-100">
                      {msg.metadata.diff}
                    </pre>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                  Thinking...
                </div>
              </div>
            )}
          </div>

          {lastAssistantActions.length > 0 && (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 bg-white px-3 py-2">
              {lastAssistantActions.map((action) => (
                <button
                  key={`${action.action}-${action.label}`}
                  onClick={() => void sendUserMessage(action.action)}
                  className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700"
                  type="button"
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault();
              void sendUserMessage(input);
            }}
            className="border-t border-slate-200 bg-white p-3"
          >
            <div className="flex items-center gap-2">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask for details, examples, or fix suggestions..."
                className="h-10 flex-1 rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              />
              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-sky-600 text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                aria-label="Send diagnosis message"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
