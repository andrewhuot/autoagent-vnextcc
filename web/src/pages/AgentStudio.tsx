import { startTransition, useState } from 'react';
import { Sparkles, MessageSquare, GitBranch, Play, Check } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { buildStudioDraft, type StudioDraft, type StudioMetricTone } from '../lib/agentStudio';
import { classNames } from '../lib/utils';

interface StudioMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
}

const SAMPLE_PROMPTS = [
  'Make BillingAgent verify invoices before answering and escalate VIP refund requests sooner.',
  'Route shipping delays straight to RefundAgent when the order is already lost in transit.',
  'Tighten orchestrator handoffs so specialists inherit the customer\'s last two actions.',
  'Add safety guardrails to prevent unauthorized PII disclosure.',
];

const INITIAL_PROMPT = SAMPLE_PROMPTS[0];
const INITIAL_DRAFT = buildStudioDraft(INITIAL_PROMPT);

function toneClasses(tone: StudioMetricTone): string {
  if (tone === 'positive') return 'border-green-200 bg-gradient-to-br from-green-50 to-emerald-50';
  if (tone === 'caution') return 'border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50';
  return 'border-gray-200 bg-white';
}

function impactClasses(impact: StudioDraft['changeSet'][number]['impact']): string {
  if (impact === 'high') return 'bg-green-100 text-green-700 border-green-200';
  if (impact === 'medium') return 'bg-amber-100 text-amber-700 border-amber-200';
  return 'bg-gray-100 text-gray-600 border-gray-200';
}

function buildAssistantReply(draft: StudioDraft): string {
  return `Queued ${draft.changeSet.length} ${draft.changeSet.length === 1 ? 'change' : 'changes'} for ${draft.focusArea}. I converted the request into prompt, policy, and rollout checks so the draft is ready for simulation.`;
}

export function AgentStudio() {
  const [composer, setComposer] = useState(INITIAL_PROMPT);
  const [draft, setDraft] = useState<StudioDraft>(INITIAL_DRAFT);
  const [messages, setMessages] = useState<StudioMessage[]>([
    {
      id: 'assistant-intro',
      role: 'assistant',
      content:
        'Describe the change in plain language. I\'ll translate it into prompt edits, routing updates, and rollout checks.',
    },
    {
      id: 'user-initial',
      role: 'user',
      content: INITIAL_PROMPT,
    },
    {
      id: 'assistant-initial',
      role: 'assistant',
      content: buildAssistantReply(INITIAL_DRAFT),
    },
  ]);

  function queueUpdate(prompt: string) {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt) return;

    const nextDraft = buildStudioDraft(trimmedPrompt);

    startTransition(() => {
      setDraft(nextDraft);
      setMessages((current) => [
        ...current,
        {
          id: `user-${current.length + 1}`,
          role: 'user',
          content: trimmedPrompt,
        },
        {
          id: `assistant-${current.length + 2}`,
          role: 'assistant',
          content: buildAssistantReply(nextDraft),
        },
      ]);
      setComposer('');
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Studio"
        description="Update an agent in natural language and watch the draft mutate live."
        icon={Sparkles}
      />

      {/* Metrics */}
      <section className="grid gap-3 sm:grid-cols-3">
        {draft.metrics.map((metric) => (
          <div
            key={metric.label}
            className={classNames('rounded-2xl border p-4', toneClasses(metric.tone))}
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">
              {metric.label}
            </p>
            <div className="mt-2 flex items-end justify-between">
              <div>
                <p className="text-2xl font-semibold tracking-tight text-gray-900">{metric.projected}</p>
                <p className="mt-0.5 text-xs text-gray-500">Current {metric.current}</p>
              </div>
              <div className="text-right text-xs text-gray-400">
                <p>Drafted from</p>
                <p>natural language</p>
              </div>
            </div>
          </div>
        ))}
      </section>

      {/* Main content grid */}
      <div className="grid gap-5 xl:grid-cols-[320px,minmax(0,1fr),340px]">
        {/* Left: Change thread */}
        <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/60">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                Change thread
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-gray-900">
                Queued changes
              </h2>
            </div>
            <div className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">
              {draft.changeSet.length} queued
            </div>
          </div>

          <div className="space-y-2.5">
            {draft.changeSet.map((change) => (
              <div key={change.id} className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
                      {change.kind}
                    </p>
                    <h3 className="mt-1.5 text-sm font-semibold leading-snug text-gray-900">
                      {change.title}
                    </h3>
                  </div>
                  <span
                    className={classNames(
                      'shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                      impactClasses(change.impact)
                    )}
                  >
                    {change.impact}
                  </span>
                </div>
                <p className="mt-2.5 text-xs leading-5 text-gray-600">{change.detail}</p>
              </div>
            ))}
          </div>

          {/* Review checklist */}
          <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
              Review checklist
            </p>
            <div className="mt-3 space-y-2.5">
              {draft.reviewChecklist.map((item) => (
                <div key={item} className="flex gap-2.5 text-xs leading-5 text-gray-600">
                  <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-600" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Center: Chat interface */}
        <section className="flex min-h-[600px] flex-col overflow-hidden rounded-3xl border border-gray-200 bg-white shadow-sm shadow-gray-100/60">
          <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3.5">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-gray-400" />
              <span className="text-sm font-medium text-gray-900">Conversation</span>
            </div>
            <div className="text-xs text-gray-400">{draft.summary}</div>
          </div>

          <div className="relative flex flex-1 flex-col">
            <div className="flex-1 space-y-3.5 overflow-y-auto p-5">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={classNames(
                    'max-w-[85%] rounded-2xl border px-4 py-3.5 text-sm leading-6',
                    message.role === 'user'
                      ? 'ml-auto border-sky-200 bg-gradient-to-br from-sky-50 to-cyan-50'
                      : 'border-gray-200 bg-gray-50/70'
                  )}
                >
                  <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
                    {message.role === 'user' ? 'Change request' : 'AutoAgent'}
                  </p>
                  <p className="text-gray-700">{message.content}</p>
                </div>
              ))}
            </div>

            <div className="border-t border-gray-200 bg-gray-50/80 p-4 backdrop-blur-sm">
              <div className="mb-3 flex flex-wrap gap-2">
                {SAMPLE_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => setComposer(prompt)}
                    className="rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600 transition hover:border-gray-300 hover:text-gray-900"
                  >
                    {prompt}
                  </button>
                ))}
              </div>

              <label className="sr-only" htmlFor="agent-studio-composer">
                Describe the agent update
              </label>
              <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
                <textarea
                  id="agent-studio-composer"
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  placeholder="Describe the agent update"
                  rows={4}
                  className="min-h-[100px] w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      queueUpdate(composer);
                    }
                  }}
                />
                <div className="flex items-center justify-between border-t border-gray-100 px-2 pt-3">
                  <div className="text-xs text-gray-400">Natural language in, scoped diff out.</div>
                  <button
                    onClick={() => queueUpdate(composer)}
                    className="rounded-lg bg-sky-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
                  >
                    Queue update
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Right: Draft preview */}
        <section className="space-y-4 rounded-3xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/60">
          <div className="rounded-xl border border-sky-100 bg-sky-50/70 p-3.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
                  Live draft
                </p>
                <h2 className="mt-1.5 text-base font-semibold tracking-tight text-gray-900">
                  {draft.title}
                </h2>
              </div>
              <div className="shrink-0 rounded-md bg-green-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-green-700">
                ready
              </div>
            </div>
            <p className="mt-2.5 text-xs leading-5 text-gray-600">{draft.summary}</p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
            <div className="flex items-center gap-2">
              <GitBranch className="h-3.5 w-3.5 text-gray-400" />
              <p className="text-xs font-medium text-gray-600">{draft.branchName}</p>
            </div>
          </div>

          {/* Before/After diff for first change */}
          {draft.changeSet[0] && (
            <div className="space-y-2.5">
              <div className="rounded-xl border border-gray-200 bg-white p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
                  Current
                </p>
                <p className="mt-2 text-xs leading-5 text-gray-600">{draft.changeSet[0].before}</p>
              </div>
              <div className="rounded-xl border border-sky-200 bg-gradient-to-br from-sky-50 to-cyan-50 p-3.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-sky-700">
                  Drafted
                </p>
                <p className="mt-2 text-xs leading-5 text-gray-700">{draft.changeSet[0].after}</p>
              </div>
            </div>
          )}

          {/* Draft actions */}
          <div className="space-y-2">
            <button className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white px-3.5 py-2.5 text-sm font-medium text-gray-700 transition hover:border-gray-300 hover:bg-gray-50">
              <Play className="h-3.5 w-3.5" />
              Simulate
            </button>
            <button className="flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 px-3.5 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700">
              <Check className="h-3.5 w-3.5" />
              Merge draft
            </button>
          </div>

          {/* All changes diff preview */}
          {draft.changeSet.length > 1 && (
            <div className="rounded-xl border border-gray-200 bg-gray-50/70 p-3.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-400">
                All changes ({draft.changeSet.length})
              </p>
              <div className="mt-3 space-y-2.5">
                {draft.changeSet.map((change) => (
                  <div key={change.id} className="rounded-lg border border-gray-200 bg-white p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="text-xs font-semibold text-gray-900">{change.title}</h3>
                      <span className="text-[10px] uppercase tracking-wide text-gray-400">
                        {change.kind}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
