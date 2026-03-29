import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain,
  Copy,
  Download,
  FileText,
  MessageSquare,
  Play,
  Send,
  Sparkles,
  UploadCloud,
  WandSparkles,
} from 'lucide-react';
import {
  useChatRefine,
  useGenerateAgent,
  useImportTranscriptArchive,
} from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import type { GeneratedAgentConfig, TranscriptReport } from '../lib/types';
import { classNames } from '../lib/utils';

type StudioMode = 'prompt' | 'transcript';
type StudioPhase = 'setup' | 'refine';

interface ChatMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
}

interface IntentSummary {
  label: string;
  count: number;
}

const PROMPT_EXAMPLES = [
  'Build a customer service agent for order tracking, cancellations, and refunds.',
  'Create an IT helpdesk agent that handles password resets, VPN issues, and hardware requests.',
  'Design a healthcare intake agent that collects symptoms, schedules appointments, and triages urgency.',
  'Build a sales qualification agent that scores leads and books demos.',
];

const REFINEMENT_EXAMPLES = [
  'Add escalation logic for VIP customers.',
  'Add a refund workflow with damage verification.',
  'Tighten safety policies around PII handling.',
];

/**
 * Intelligence Studio is the fastest path from a prompt or transcript archive
 * to a live, inspectable agent configuration in this app.
 */
export function IntelligenceStudio() {
  const navigate = useNavigate();
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const [mode, setMode] = useState<StudioMode>('prompt');
  const [phase, setPhase] = useState<StudioPhase>('setup');
  const [prompt, setPrompt] = useState('');
  const [transcriptReport, setTranscriptReport] = useState<TranscriptReport | null>(null);
  const [agentConfig, setAgentConfig] = useState<GeneratedAgentConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [composer, setComposer] = useState('');

  const importMutation = useImportTranscriptArchive();
  const generateMutation = useGenerateAgent();
  const refineMutation = useChatRefine();

  useEffect(() => {
    if (typeof chatEndRef.current?.scrollIntoView === 'function') {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const yamlPreview = agentConfig ? configToYaml(agentConfig) : '';
  const transcriptIntents = transcriptReport ? buildIntentSummaries(transcriptReport) : [];
  const patternSignals = transcriptReport ? buildPatternSignals(transcriptReport) : [];

  function resetStudio() {
    setPhase('setup');
    setPrompt('');
    setTranscriptReport(null);
    setAgentConfig(null);
    setMessages([]);
    setComposer('');
    setMode('prompt');
  }

  function handlePromptGenerate() {
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      toastError('Prompt required', 'Describe the agent you want to build.');
      return;
    }

    generateMutation.mutate(
      { prompt: nextPrompt },
      {
        onSuccess: (config) => {
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            buildAssistantMessage(
              `I drafted **${config.metadata.agent_name}** with ${config.tools.length} tools, ${config.routing_rules.length} routing rules, and ${config.policies.length} policies. Tell me what to refine next.`
            ),
          ]);
          toastSuccess('Agent generated', `${config.metadata.agent_name} is ready for refinement.`);
        },
        onError: (error) => {
          toastError('Generation failed', error.message);
        },
      }
    );
  }

  function handleTranscriptGenerate() {
    if (!transcriptReport) {
      toastError('Transcript analysis required', 'Upload transcripts before generating the agent.');
      return;
    }

    generateMutation.mutate(
      {
        prompt: `Generate an agent from transcript insights in ${transcriptReport.archive_name}`,
        transcript_report_id: transcriptReport.report_id,
      },
      {
        onSuccess: (config) => {
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            buildAssistantMessage(
              `I turned the transcript analysis into **${config.metadata.agent_name}**. The config already reflects the top intent gaps, workflow signals, and FAQ patterns from the upload.`
            ),
          ]);
          toastSuccess('Agent generated', `${config.metadata.agent_name} is ready for refinement.`);
        },
        onError: (error) => {
          toastError('Generation failed', error.message);
        },
      }
    );
  }

  async function handleTranscriptUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const archiveBase64 = await fileToBase64(file);
      importMutation.mutate(
        {
          archive_name: file.name,
          archive_base64: archiveBase64,
        },
        {
          onSuccess: (report) => {
            setTranscriptReport(report);
            toastSuccess(
              'Transcripts analyzed',
              `${report.conversation_count} conversations processed from ${report.archive_name}.`
            );
          },
          onError: (error) => {
            toastError('Import failed', error.message);
          },
        }
      );
    } catch (error) {
      toastError('Import failed', error instanceof Error ? error.message : String(error));
    } finally {
      event.target.value = '';
    }
  }

  function handleRefineSend() {
    const message = composer.trim();
    if (!message || !agentConfig) {
      return;
    }

    setMessages((current) => [...current, buildUserMessage(message)]);
    setComposer('');

    refineMutation.mutate(
      {
        message,
        config: agentConfig,
      },
      {
        onSuccess: (result) => {
          setAgentConfig(result.config);
          setMessages((current) => [...current, buildAssistantMessage(result.response)]);
        },
        onError: (error) => {
          toastError('Refinement failed', error.message);
          setMessages((current) => [
            ...current,
            buildAssistantMessage(`I hit an error while applying that change: ${error.message}`),
          ]);
        },
      }
    );
  }

  async function handleCopyYaml() {
    if (!agentConfig || !navigator.clipboard?.writeText) {
      return;
    }

    try {
      await navigator.clipboard.writeText(configToYaml(agentConfig));
      toastSuccess('Copied', 'The YAML config is in your clipboard.');
    } catch (error) {
      toastError('Copy failed', error instanceof Error ? error.message : String(error));
    }
  }

  function handleExport() {
    if (!agentConfig) {
      return;
    }

    const blob = new Blob([configToYaml(agentConfig)], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slugify(agentConfig.metadata.agent_name)}.yaml`;
    link.click();
    URL.revokeObjectURL(url);
    toastSuccess('Config exported', 'Downloaded the YAML config.');
  }

  if (phase === 'setup') {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Intelligence Studio"
          description="Start from a prompt or a transcript archive, then refine the generated agent in a live YAML workspace."
        />

        <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
          Mock mode friendly: the studio generates realistic configs and transcript insights without requiring API keys.
        </div>

        <StudioModeToggle mode={mode} onChange={setMode} />

        {mode === 'prompt' ? (
          <section className="rounded-3xl border border-gray-200 bg-white shadow-sm">
            <div className="border-b border-gray-100 px-6 py-5">
              <div className="flex items-start gap-4">
                <div className="rounded-2xl bg-gray-900 p-3 text-white">
                  <Brain className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900">Start from Prompt</h3>
                  <p className="mt-1 text-sm leading-relaxed text-gray-600">
                    Describe the agent you want to build and the studio will generate a structured config you can refine conversationally.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-5 px-6 py-6">
              <textarea
                aria-label="Agent description"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={7}
                placeholder="Describe the agent you want to build..."
                className="min-h-[220px] w-full rounded-2xl border border-gray-200 bg-gray-50 px-5 py-4 text-sm leading-relaxed text-gray-900 outline-none transition focus:border-sky-400 focus:bg-white focus:ring-4 focus:ring-sky-100"
              />

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
                  Example prompts
                </p>
                <div className="flex flex-wrap gap-2">
                  {PROMPT_EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => setPrompt(example)}
                      className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-gray-500">
                  Start with the job, channels, policies, and any must-have tools or routing rules.
                </div>
                <button
                  type="button"
                  onClick={handlePromptGenerate}
                  disabled={generateMutation.isPending || !prompt.trim()}
                  className="inline-flex items-center gap-2 rounded-2xl bg-gray-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <WandSparkles className="h-4 w-4" />
                  {generateMutation.isPending ? 'Generating...' : 'Generate Agent'}
                </button>
              </div>
            </div>
          </section>
        ) : (
          <section className="rounded-3xl border border-gray-200 bg-white shadow-sm">
            <div className="border-b border-gray-100 px-6 py-5">
              <div className="flex items-start gap-4">
                <div className="rounded-2xl bg-gray-900 p-3 text-white">
                  <FileText className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold text-gray-900">Start from Transcripts</h3>
                  <p className="mt-1 text-sm leading-relaxed text-gray-600">
                    Upload ZIP, JSON, CSV, TXT, or JSONL transcript files. The studio extracts intents, patterns, and FAQ signals before generating the agent.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-5 px-6 py-6">
              <label className="flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50 px-6 py-12 text-center transition hover:border-gray-300 hover:bg-gray-100">
                <UploadCloud className="h-10 w-10 text-gray-400" />
                <div>
                  <p className="text-sm font-semibold text-gray-700">Upload transcript files</p>
                  <p className="mt-1 text-xs text-gray-500">Supports ZIP, JSON, CSV, TXT, and JSONL</p>
                </div>
                <input
                  aria-label="Upload transcript files"
                  type="file"
                  accept=".zip,.json,.jsonl,.csv,.txt,.md"
                  className="hidden"
                  onChange={handleTranscriptUpload}
                />
              </label>

              {importMutation.isPending && (
                <div className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
                  Analyzing transcripts...
                </div>
              )}

              {transcriptReport && (
                <div className="space-y-5">
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <MetricCard label="Conversations" value={String(transcriptReport.conversation_count)} />
                    <MetricCard label="Languages" value={transcriptReport.languages.join(', ') || 'n/a'} />
                    <MetricCard label="Insights" value={String(transcriptReport.insights.length)} />
                    <MetricCard label="FAQs" value={String(transcriptReport.faq_entries.length)} />
                  </div>

                  <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                    <AnalysisSection title="Top Intents" eyebrow="Coverage">
                      <div className="space-y-2">
                        {transcriptIntents.map((intent) => (
                          <div
                            key={intent.label}
                            className="flex items-center justify-between rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2"
                          >
                            <span className="text-sm font-medium text-gray-800">{humanizeLabel(intent.label)}</span>
                            <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-gray-600">
                              {intent.count}
                            </span>
                          </div>
                        ))}
                      </div>
                    </AnalysisSection>

                    <AnalysisSection title="Pattern Signals" eyebrow="What stood out">
                      <div className="space-y-3">
                        {patternSignals.map((signal, index) => (
                          <div
                            key={`${signal.title}-${index}`}
                            className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3"
                          >
                            <p className="text-sm font-semibold text-gray-900">{signal.title}</p>
                            <p className="mt-1 text-sm leading-relaxed text-gray-600">{signal.summary}</p>
                          </div>
                        ))}
                      </div>
                    </AnalysisSection>
                  </div>

                  <AnalysisSection title="Extracted FAQs" eyebrow="Reusable responses">
                    <div className="space-y-3">
                      {transcriptReport.faq_entries.slice(0, 4).map((faq) => (
                        <div
                          key={`${faq.intent}-${faq.question}`}
                          className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3"
                        >
                          <p className="text-sm font-semibold text-gray-900">{faq.question}</p>
                          <p className="mt-1 text-sm leading-relaxed text-gray-600">{faq.answer}</p>
                        </div>
                      ))}
                    </div>
                  </AnalysisSection>

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm text-gray-500">
                      The generated agent will incorporate the transcript gaps, workflow suggestions, and FAQ patterns.
                    </div>
                    <button
                      type="button"
                      onClick={handleTranscriptGenerate}
                      disabled={generateMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-2xl bg-gray-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <WandSparkles className="h-4 w-4" />
                      {generateMutation.isPending ? 'Generating...' : 'Generate Agent'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Intelligence Studio"
        description={
          agentConfig
            ? `Refining ${agentConfig.metadata.agent_name} through conversation and live YAML inspection.`
            : 'Refine the generated agent.'
        }
        actions={
          <button
            type="button"
            onClick={resetStudio}
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-50 hover:text-gray-900"
          >
            Start Over
          </button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(360px,1fr)]">
        <section className="flex min-h-[720px] flex-col rounded-3xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-gray-500" />
              <h3 className="text-base font-semibold text-gray-900">Conversational Refinement</h3>
            </div>
            <p className="mt-1 text-sm text-gray-500">
              Ask for policy changes, new tools, routing updates, or safer behavior. Each reply updates the live YAML preview.
            </p>
          </div>

          <div className="border-b border-gray-100 px-5 py-3">
            <div className="flex flex-wrap gap-2">
              {REFINEMENT_EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setComposer(example)}
                  className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            {messages.map((message) => (
              <ChatBubble key={message.id} message={message} />
            ))}
            {refineMutation.isPending && (
              <div className="max-w-[85%] rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
                Updating the config...
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="border-t border-gray-100 px-5 py-4">
            <div className="flex gap-3">
              <textarea
                aria-label="Refinement message"
                value={composer}
                onChange={(event) => setComposer(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    handleRefineSend();
                  }
                }}
                rows={3}
                placeholder="Tell the studio what to change next..."
                className="min-h-[84px] flex-1 resize-none rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-relaxed text-gray-900 outline-none transition focus:border-sky-400 focus:bg-white focus:ring-4 focus:ring-sky-100"
                disabled={refineMutation.isPending}
              />
              <button
                type="button"
                aria-label="Send refinement message"
                onClick={handleRefineSend}
                disabled={refineMutation.isPending || !composer.trim()}
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gray-900 text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>

        <section className="flex min-h-[720px] flex-col rounded-3xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Brain className="h-4 w-4 text-gray-500" />
                  <h3 className="text-base font-semibold text-gray-900">Live YAML Config</h3>
                </div>
                <p className="mt-1 text-sm text-gray-500">
                  Inspect the generated config as YAML while you refine the agent.
                </p>
              </div>
              <button
                type="button"
                onClick={handleCopyYaml}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-50 hover:text-gray-900"
              >
                <Copy className="h-4 w-4" />
                Copy
              </button>
            </div>
          </div>

          {agentConfig && (
            <>
              <div className="grid grid-cols-3 gap-px border-b border-gray-100 bg-gray-100">
                <MetricCard label="Tools" value={String(agentConfig.tools.length)} compact />
                <MetricCard label="Policies" value={String(agentConfig.policies.length)} compact />
                <MetricCard label="Routes" value={String(agentConfig.routing_rules.length)} compact />
              </div>

              <div className="border-b border-gray-100 px-5 py-4">
                <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
                    Agent
                  </p>
                  <p className="mt-2 text-sm font-semibold text-gray-900">
                    {agentConfig.metadata.agent_name}
                  </p>
                  <p className="mt-1 text-sm text-gray-500">
                    {agentConfig.metadata.created_from === 'transcript'
                      ? 'Generated from transcript intelligence.'
                      : 'Generated from a natural-language prompt.'}
                  </p>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto bg-[#0B1020] px-0 py-0">
                <YamlPreview yaml={yamlPreview} />
              </div>

              <div className="grid grid-cols-1 gap-2 border-t border-gray-100 p-4 sm:grid-cols-3">
                <button
                  type="button"
                  onClick={() => navigate('/evals?new=1')}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
                >
                  <Sparkles className="h-4 w-4" />
                  Generate Evals
                </button>
                <button
                  type="button"
                  onClick={handleExport}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
                >
                  <Download className="h-4 w-4" />
                  Export
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/evals?run=1')}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm font-semibold text-sky-700 transition hover:bg-sky-100"
                >
                  <Play className="h-4 w-4" />
                  Run Eval
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function StudioModeToggle({
  mode,
  onChange,
}: {
  mode: StudioMode;
  onChange: (mode: StudioMode) => void;
}) {
  return (
    <div className="inline-flex rounded-2xl border border-gray-200 bg-white p-1 shadow-sm">
      <button
        type="button"
        onClick={() => onChange('prompt')}
        className={classNames(
          'inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition',
          mode === 'prompt'
            ? 'bg-gray-900 text-white'
            : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
        )}
      >
        <Sparkles className="h-4 w-4" />
        Start from Prompt
      </button>
      <button
        type="button"
        onClick={() => onChange('transcript')}
        className={classNames(
          'inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition',
          mode === 'transcript'
            ? 'bg-gray-900 text-white'
            : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
        )}
      >
        <FileText className="h-4 w-4" />
        Start from Transcripts
      </button>
    </div>
  );
}

function AnalysisSection({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">{eyebrow}</p>
      <h4 className="mt-2 text-base font-semibold text-gray-900">{title}</h4>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className={classNames(compact ? 'bg-white px-3 py-3 text-center' : 'rounded-2xl border border-gray-200 bg-white p-4')}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">{label}</p>
      <p className={classNames('mt-2 font-semibold text-gray-900', compact ? 'text-lg' : 'text-2xl')}>
        {value}
      </p>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const assistant = message.role === 'assistant';
  return (
    <div className={classNames('flex', assistant ? 'justify-start' : 'justify-end')}>
      <div
        className={classNames(
          'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          assistant
            ? 'border border-gray-200 bg-gray-50 text-gray-700'
            : 'bg-gray-900 text-white'
        )}
      >
        {message.content.split('\n').map((line, index) => (
          <p key={`${message.id}-${index}`} className={index === 0 ? '' : 'mt-2'}>
            {renderRichLine(line)}
          </p>
        ))}
      </div>
    </div>
  );
}

function YamlPreview({ yaml }: { yaml: string }) {
  const lines = yaml.split('\n');

  return (
    <div data-testid="yaml-preview" className="font-mono text-[12px] leading-6 text-slate-200">
      {lines.map((line, index) => (
        <div
          key={`${index}-${line}`}
          className="grid grid-cols-[48px_minmax(0,1fr)] items-start border-b border-white/5 px-4"
        >
          <span className="select-none pr-3 text-right text-slate-500">{index + 1}</span>
          <code className="overflow-x-auto py-1.5">{highlightYamlLine(line)}</code>
        </div>
      ))}
    </div>
  );
}

function highlightYamlLine(line: string): ReactNode {
  if (!line) {
    return <span>&nbsp;</span>;
  }

  const keyMatch = line.match(/^(\s*-\s+)?([A-Za-z_]+):(.*)$/);
  if (!keyMatch) {
    return <span className="text-slate-200">{line}</span>;
  }

  const [, listPrefix = '', key, rest] = keyMatch;
  return (
    <>
      {listPrefix && <span className="text-slate-500">{listPrefix}</span>}
      <span className="text-sky-300">{key}</span>
      <span className="text-slate-500">:</span>
      {rest ? <span className="text-emerald-200">{rest}</span> : null}
    </>
  );
}

function renderRichLine(line: string): ReactNode {
  if (line.startsWith('- ')) {
    return (
      <span className="flex gap-2">
        <span className="text-gray-400">•</span>
        <span>{line.slice(2)}</span>
      </span>
    );
  }

  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={`${part}-${index}`} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function buildIntentSummaries(report: TranscriptReport): IntentSummary[] {
  const counts = new Map<string, number>();

  for (const conversation of report.conversations ?? []) {
    if (conversation.intent) {
      counts.set(conversation.intent, (counts.get(conversation.intent) ?? 0) + 1);
    }
  }

  if (counts.size === 0) {
    for (const faq of report.faq_entries ?? []) {
      if (faq.intent) {
        counts.set(faq.intent, (counts.get(faq.intent) ?? 0) + 1);
      }
    }
  }

  if (counts.size === 0) {
    for (const item of report.missing_intents ?? []) {
      if (item.intent) {
        counts.set(item.intent, Number(item.count ?? 1));
      }
    }
  }

  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => ({ label, count }));
}

function buildPatternSignals(report: TranscriptReport) {
  const insights = (report.insights ?? []).slice(0, 2).map((insight) => ({
    title: insight.title,
    summary: insight.summary,
  }));
  const workflowSignals = (report.workflow_suggestions ?? []).slice(0, 2).map((workflow) => ({
    title: workflow.title,
    summary: workflow.description,
  }));

  const combined = [...insights, ...workflowSignals];
  if (combined.length > 0) {
    return combined;
  }

  return [
    {
      title: 'No dominant pattern detected',
      summary: 'Upload more transcripts to extract stronger workflow and escalation signals.',
    },
  ];
}

function buildAssistantMessage(content: string): ChatMessage {
  return {
    id: `assistant-${crypto.randomUUID()}`,
    role: 'assistant',
    content,
  };
}

function buildUserMessage(content: string): ChatMessage {
  return {
    id: `user-${crypto.randomUUID()}`,
    role: 'user',
    content,
  };
}

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const [, payload] = result.split(',');
      resolve(payload || result);
    };
    reader.readAsDataURL(file);
  });
}

function slugify(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function humanizeLabel(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function configToYaml(config: GeneratedAgentConfig): string {
  const lines: string[] = [
    'metadata:',
    `  agent_name: ${config.metadata.agent_name}`,
    `  version: ${config.metadata.version}`,
    `  created_from: ${config.metadata.created_from}`,
    '',
    'system_prompt: |',
    ...config.system_prompt.split('\n').map((line) => `  ${line}`),
    '',
    'tools:',
  ];

  for (const tool of config.tools) {
    lines.push(`  - name: ${tool.name}`);
    lines.push(`    description: ${tool.description}`);
    lines.push('    parameters:');
    if (tool.parameters.length === 0) {
      lines.push('      - none');
    } else {
      for (const parameter of tool.parameters) {
        lines.push(`      - ${parameter}`);
      }
    }
  }

  lines.push('', 'routing_rules:');
  for (const rule of config.routing_rules) {
    lines.push(`  - condition: ${JSON.stringify(rule.condition)}`);
    lines.push(`    action: ${rule.action}`);
    lines.push(`    priority: ${rule.priority}`);
  }

  lines.push('', 'policies:');
  for (const policy of config.policies) {
    lines.push(`  - name: ${policy.name}`);
    lines.push(`    enforcement: ${policy.enforcement}`);
    lines.push(`    description: ${JSON.stringify(policy.description)}`);
  }

  lines.push('', 'eval_criteria:');
  for (const criterion of config.eval_criteria) {
    lines.push(`  - name: ${criterion.name}`);
    lines.push(`    weight: ${criterion.weight}`);
    lines.push(`    description: ${JSON.stringify(criterion.description)}`);
  }

  return lines.join('\n');
}
