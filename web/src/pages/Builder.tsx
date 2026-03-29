import { startTransition, useEffect, useRef, useState } from 'react';
import { Download, Play, Send, Sparkles } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import {
  exportBuilderConfig,
  sendBuilderMessage,
  type BuilderConfig,
  type BuilderSessionPayload,
} from '../lib/builder-chat-api';
import { classNames } from '../lib/utils';

const STARTER_PROMPTS = [
  'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status',
  'Add a tool for checking flight status',
  'Make it more empathetic',
  'Add a policy that it should never reveal internal codes',
];

function StatPill({ label, testId }: { label: string; testId?: string }) {
  return (
    <div
      data-testid={testId}
      className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-600"
    >
      {label}
    </div>
  );
}

function ConfigLine({ line }: { line: string }) {
  const keyMatch = line.match(/^(\s*)"([^"]+)":\s(.*)$/);
  if (!keyMatch) {
    return <div className="whitespace-pre-wrap text-slate-400">{line}</div>;
  }

  const [, indent, key, value] = keyMatch;
  const valueClass =
    value.startsWith('"') ? 'text-sky-700' : value.startsWith('[') || value.startsWith('{') ? 'text-slate-500' : 'text-emerald-700';

  return (
    <div className="whitespace-pre-wrap">
      <span className="text-slate-400">{indent}</span>
      <span className="text-rose-600">"{key}"</span>
      <span className="text-slate-400">: </span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}

function ConfigPreview({ config }: { config: BuilderConfig | null }) {
  if (!config) {
    return (
      <div
        data-testid="builder-config-preview"
        className="rounded-2xl border border-dashed border-gray-200 bg-gray-50/70 p-4 text-sm text-gray-500"
      >
        Start the conversation on the left and the draft config will appear here in real time.
      </div>
    );
  }

  const content = JSON.stringify(config, null, 2).split('\n');
  return (
    <div
      data-testid="builder-config-preview"
      className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950"
    >
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-xs text-slate-400">
        <span>Live Config</span>
        <span>JSON preview</span>
      </div>
      <pre className="overflow-x-auto px-4 py-4 text-xs leading-6">
        {content.map((line, index) => (
          <ConfigLine key={`${index}-${line}`} line={line} />
        ))}
      </pre>
    </div>
  );
}

export function Builder() {
  const [composer, setComposer] = useState('');
  const [session, setSession] = useState<BuilderSessionPayload | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  async function submitMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || pending) {
      return;
    }

    setPending(true);
    setError(null);

    try {
      const nextSession = await sendBuilderMessage({
        message: trimmed,
        session_id: session?.session_id ?? undefined,
      });

      startTransition(() => {
        setSession(nextSession);
        setComposer('');
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Builder request failed');
    } finally {
      setPending(false);
    }
  }

  async function handleExport() {
    if (!session?.session_id || pending) {
      return;
    }

    setPending(true);
    setError(null);

    try {
      const payload = await exportBuilderConfig({
        session_id: session.session_id,
        format: 'yaml',
      });

      const blob = new Blob([payload.content], { type: payload.content_type });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = payload.filename;
      anchor.style.display = 'none';
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => {
        URL.revokeObjectURL(url);
        anchor.remove();
      }, 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Config export failed');
    } finally {
      setPending(false);
    }
  }

  const messages = session?.messages ?? [
    {
      message_id: 'builder-starter',
      role: 'assistant' as const,
      content:
        'Describe the agent you want to build. I will draft the config, update it as you refine it, and keep the preview in sync.',
      created_at: Date.now(),
    },
  ];

  useEffect(() => {
    const container = messageListRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [messages.length]);

  return (
    <div data-testid="builder-page" className="space-y-6">
      <PageHeader
        title="Builder"
        description="Describe the agent you want to build, refine it in conversation, and watch the config update live."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]">
        <section className="flex min-h-[560px] flex-col overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-sm shadow-gray-100/70 lg:min-h-[640px] xl:min-h-[720px]">
          <div className="border-b border-gray-200 px-5 py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                  Conversational Builder
                </p>
                <h3 className="mt-1 text-lg font-semibold tracking-tight text-gray-900">
                  Describe the agent you want to build
                </h3>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
                <Sparkles className="h-3.5 w-3.5" />
                Mock mode
              </div>
            </div>
          </div>

          <div
            ref={messageListRef}
            data-testid="builder-message-list"
            className="flex-1 space-y-4 overflow-y-auto px-5 py-5"
          >
            {messages.map((message) => (
              <div
                key={message.message_id}
                className={classNames(
                  'max-w-[88%] rounded-2xl border px-4 py-3 text-sm leading-6',
                  message.role === 'user'
                    ? 'ml-auto border-sky-200 bg-sky-50 text-sky-950'
                    : 'border-gray-200 bg-gray-50 text-gray-700'
                )}
              >
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                  {message.role === 'user' ? 'You' : 'Builder'}
                </p>
                <p>{message.content}</p>
              </div>
            ))}

            {error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
          </div>

          <div className="border-t border-gray-200 bg-gray-50/80 px-5 py-4">
            <div className="mb-3 flex flex-wrap gap-2">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setComposer(prompt)}
                  className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 transition hover:border-gray-300 hover:text-gray-900"
                >
                  {prompt}
                </button>
              ))}
            </div>

            <div className="rounded-[24px] border border-gray-200 bg-white p-3 shadow-sm">
              <textarea
                data-testid="builder-composer"
                value={composer}
                onChange={(event) => setComposer(event.target.value)}
                placeholder="Describe the agent you want to build..."
                rows={4}
                className="min-h-[112px] w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400"
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void submitMessage(composer);
                  }
                }}
              />
              <div className="flex items-center justify-between border-t border-gray-100 px-2 pt-3">
                <p className="text-xs text-gray-400">
                  Ask for a base agent, then refine tools, policies, tone, and evals.
                </p>
                <button
                  data-testid="builder-send"
                  onClick={() => void submitMessage(composer)}
                  disabled={pending}
                  className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Send className="h-4 w-4" />
                  Send
                </button>
              </div>
            </div>
          </div>
        </section>

        <aside className="flex min-h-[560px] flex-col rounded-[28px] border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/70 lg:min-h-[640px] xl:min-h-[720px]">
          <div className="mb-4">
            <h3 className="text-lg font-semibold tracking-tight text-gray-900">Live Config</h3>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
              Preview
            </p>
            <p
              data-testid="builder-preview-agent-name"
              className="mt-1 text-lg font-semibold tracking-tight text-gray-900"
            >
              {session?.config.agent_name ?? 'Preview pending'}
            </p>
            <p className="mt-1 text-sm text-gray-600">
              The preview stays in sync with the conversation and is ready to export at any point.
            </p>
          </div>

          <div className="mb-4 flex flex-wrap gap-2">
            <StatPill testId="builder-stat-tools" label={`${session?.stats.tool_count ?? 0} tools`} />
            <StatPill
              testId="builder-stat-policies"
              label={`${session?.stats.policy_count ?? 0} policies`}
            />
            <StatPill
              testId="builder-stat-routes"
              label={`${session?.stats.routing_rule_count ?? 0} routes`}
            />
          </div>

          <div className="space-y-4">
            <ConfigPreview config={session?.config ?? null} />

            <div className="rounded-2xl border border-gray-200 bg-gray-50/70 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                Eval Readiness
              </p>
              <p data-testid="builder-eval-summary" className="mt-2 text-sm font-medium text-gray-900">
                {session?.evals ? `${session.evals.case_count} draft evals` : 'No evals generated yet'}
              </p>
              <div className="mt-3 space-y-2">
                {(session?.evals?.scenarios ?? []).map((scenario) => (
                  <div key={scenario.name} className="rounded-xl border border-gray-200 bg-white px-3 py-2">
                    <p className="text-xs font-semibold text-gray-900">{scenario.name}</p>
                    <p className="mt-1 text-xs leading-5 text-gray-600">{scenario.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-auto flex gap-3 pt-4">
            <button
              data-testid="builder-download"
              onClick={handleExport}
              disabled={!session?.session_id || pending}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              Download Config
            </button>
            <button
              data-testid="builder-run-eval"
              onClick={() => void submitMessage('Generate evals for this')}
              disabled={!session?.session_id || pending}
              className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-sky-600 px-3.5 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Play className="h-4 w-4" />
              Run Eval
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
