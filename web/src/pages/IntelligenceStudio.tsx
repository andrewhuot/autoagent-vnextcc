import { useState, useRef, useEffect, type ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain,
  ChevronDown,
  Copy,
  Download,
  FileText,
  MessageSquare,
  Play,
  Send,
  Sparkles,
  UploadCloud,
  Zap,
} from 'lucide-react';
import {
  useChatRefine,
  useGenerateAgent,
  useImportTranscriptArchive,
} from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import type { GeneratedAgentConfig, TranscriptReport } from '../lib/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function configToYaml(config: GeneratedAgentConfig): string {
  const lines: string[] = [];
  const meta = config.metadata;
  lines.push(`# Agent: ${meta.agent_name}`);
  lines.push(`# Version: ${meta.version}`);
  lines.push(`# Created from: ${meta.created_from}`);
  lines.push('');
  lines.push('system_prompt: |');
  for (const line of config.system_prompt.split('\n')) {
    lines.push(`  ${line}`);
  }
  lines.push('');
  lines.push('tools:');
  for (const tool of config.tools) {
    lines.push(`  - name: ${tool.name}`);
    lines.push(`    description: ${tool.description}`);
    if (tool.parameters.length > 0) {
      lines.push(`    parameters: [${tool.parameters.join(', ')}]`);
    }
  }
  lines.push('');
  lines.push('routing_rules:');
  for (const rule of config.routing_rules) {
    lines.push(`  - condition: "${rule.condition}"`);
    lines.push(`    action: ${rule.action}`);
    lines.push(`    priority: ${rule.priority}`);
  }
  lines.push('');
  lines.push('policies:');
  for (const policy of config.policies) {
    lines.push(`  - name: ${policy.name}`);
    lines.push(`    description: "${policy.description}"`);
    lines.push(`    enforcement: ${policy.enforcement}`);
  }
  lines.push('');
  lines.push('eval_criteria:');
  for (const criterion of config.eval_criteria) {
    lines.push(`  - name: ${criterion.name}`);
    lines.push(`    weight: ${criterion.weight}`);
    lines.push(`    description: "${criterion.description}"`);
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type Mode = 'prompt' | 'transcript';
type Phase = 'input' | 'refine';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const EXAMPLE_PROMPTS = [
  'Build a customer service agent for order tracking, cancellations, and refunds',
  'Create an IT helpdesk agent that handles password resets, VPN issues, and hardware requests',
  'Design a healthcare intake agent that collects symptoms, schedules appointments, and triages urgency',
  'Build a sales qualification agent that scores leads and books demos',
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function IntelligenceStudio() {
  const navigate = useNavigate();

  // Mode & phase
  const [mode, setMode] = useState<Mode>('prompt');
  const [phase, setPhase] = useState<Phase>('input');

  // Prompt mode
  const [prompt, setPrompt] = useState('');

  // Transcript mode
  const [transcriptReport, setTranscriptReport] = useState<TranscriptReport | null>(null);

  // Agent config (shared across both modes after generation)
  const [agentConfig, setAgentConfig] = useState<GeneratedAgentConfig | null>(null);

  // Chat refinement
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [composer, setComposer] = useState('');
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Preview panel
  const [expandedSection, setExpandedSection] = useState<string | null>('system_prompt');

  // Mutations
  const generateMutation = useGenerateAgent();
  const chatMutation = useChatRefine();
  const importMutation = useImportTranscriptArchive();

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Handlers ────────────────────────────────────────────────────────────

  function handleGenerate() {
    if (!prompt.trim()) {
      toastError('Prompt required', 'Describe the agent you want to build.');
      return;
    }
    generateMutation.mutate(
      { prompt: prompt.trim() },
      {
        onSuccess: (config) => {
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            {
              id: 'assistant-0',
              role: 'assistant',
              content: `I've built an initial agent config: **${config.metadata.agent_name}** with ${config.tools.length} tools, ${config.routing_rules.length} routing rules, and ${config.policies.length} policies.\n\nTell me what to add, change, or remove. For example:\n- "Add escalation logic for VIP customers"\n- "Add a refund handling flow"\n- "Add safety policies for PII protection"`,
            },
          ]);
          toastSuccess('Agent generated', `${config.metadata.agent_name} is ready for refinement.`);
        },
        onError: (error) => toastError('Generation failed', error.message),
      }
    );
  }

  function handleGenerateFromTranscript() {
    if (!transcriptReport) return;
    generateMutation.mutate(
      {
        prompt: `Build an agent based on transcript analysis: ${transcriptReport.archive_name}`,
        transcript_report_id: transcriptReport.report_id,
      },
      {
        onSuccess: (config) => {
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            {
              id: 'assistant-0',
              role: 'assistant',
              content: `I've analyzed **${transcriptReport.conversation_count} conversations** from "${transcriptReport.archive_name}" and generated an initial agent config: **${config.metadata.agent_name}**.\n\nThe config includes ${config.tools.length} tools, ${config.routing_rules.length} routing rules, and ${config.policies.length} policies based on the transcript patterns.\n\nRefine it by telling me what to add or change.`,
            },
          ]);
          toastSuccess('Agent generated from transcripts', config.metadata.agent_name);
        },
        onError: (error) => toastError('Generation failed', error.message),
      }
    );
  }

  function handleChatSend() {
    if (!composer.trim() || !agentConfig) return;
    const userMsg: ChatMessage = {
      id: `user-${messages.length}`,
      role: 'user',
      content: composer.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    const currentComposer = composer.trim();
    setComposer('');

    chatMutation.mutate(
      { message: currentComposer, config: agentConfig },
      {
        onSuccess: (result) => {
          setAgentConfig(result.config);
          setMessages((prev) => [
            ...prev,
            {
              id: `assistant-${prev.length}`,
              role: 'assistant',
              content: result.response,
            },
          ]);
        },
        onError: (error) => {
          toastError('Refinement failed', error.message);
          setMessages((prev) => [
            ...prev,
            {
              id: `assistant-err-${prev.length}`,
              role: 'assistant',
              content: `Error: ${error.message}. Try again.`,
            },
          ]);
        },
      }
    );
  }

  async function handleArchiveUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const archiveBase64 = await fileToBase64(file);
      importMutation.mutate(
        { archive_name: file.name, archive_base64: archiveBase64 },
        {
          onSuccess: (report) => {
            setTranscriptReport(report as unknown as TranscriptReport);
            toastSuccess(
              'Transcript archive imported',
              `${(report as unknown as TranscriptReport).conversation_count} conversations analyzed.`
            );
          },
          onError: (error) => toastError('Import failed', error.message),
        }
      );
    } catch (error) {
      toastError('Import failed', error instanceof Error ? error.message : String(error));
    } finally {
      event.target.value = '';
    }
  }

  function handleExportConfig() {
    if (!agentConfig) return;
    const yaml = configToYaml(agentConfig);
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${agentConfig.metadata.agent_name.replace(/\s+/g, '-').toLowerCase()}-config.yaml`;
    a.click();
    URL.revokeObjectURL(url);
    toastSuccess('Config exported', 'YAML file downloaded.');
  }

  function handleCopyConfig() {
    if (!agentConfig) return;
    navigator.clipboard.writeText(configToYaml(agentConfig));
    toastSuccess('Copied', 'Config YAML copied to clipboard.');
  }

  function toggleSection(section: string) {
    setExpandedSection((prev) => (prev === section ? null : section));
  }

  // ── Render: Input Phase ─────────────────────────────────────────────────

  if (phase === 'input') {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Intelligence Studio"
          description="Go from zero to a working agent. Start from a prompt or upload transcripts."
        />

        {/* Mode Selector */}
        <div className="flex gap-1 rounded-xl bg-gray-100 p-1">
          <button
            onClick={() => setMode('prompt')}
            className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold transition ${
              mode === 'prompt'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Sparkles className="mr-2 inline-block h-4 w-4" />
            Start from Prompt
          </button>
          <button
            onClick={() => setMode('transcript')}
            className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold transition ${
              mode === 'transcript'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <FileText className="mr-2 inline-block h-4 w-4" />
            Start from Transcripts
          </button>
        </div>

        {/* Prompt Mode */}
        {mode === 'prompt' && (
          <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl bg-gray-900 p-2.5 text-white">
                <Brain className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Describe Your Agent</h3>
                <p className="text-sm text-gray-500">Tell us what you want your agent to do. We'll generate the config.</p>
              </div>
            </div>

            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={5}
              className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm text-gray-800 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              placeholder="Build a customer service agent that handles order tracking, cancellations, and refunds. It should verify identity before making changes and escalate when the customer doesn't have their order number..."
            />

            <div className="mt-4 flex flex-wrap gap-2">
              {EXAMPLE_PROMPTS.map((example) => (
                <button
                  key={example}
                  onClick={() => setPrompt(example)}
                  className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:border-gray-300 hover:bg-gray-100"
                >
                  {example}
                </button>
              ))}
            </div>

            <button
              onClick={handleGenerate}
              disabled={generateMutation.isPending || !prompt.trim()}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              <Zap className="h-4 w-4" />
              {generateMutation.isPending ? 'Generating...' : 'Generate Agent'}
            </button>
          </section>
        )}

        {/* Transcript Mode */}
        {mode === 'transcript' && (
          <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl bg-gray-900 p-2.5 text-white">
                <FileText className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Upload Transcripts</h3>
                <p className="text-sm text-gray-500">
                  Upload a ZIP, JSON, CSV, or TXT file with conversation transcripts.
                </p>
              </div>
            </div>

            {!transcriptReport && (
              <label className="flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-10 transition hover:border-gray-400 hover:bg-gray-100">
                <UploadCloud className="h-10 w-10 text-gray-400" />
                <span className="text-sm font-medium text-gray-600">
                  Drop transcript files here or click to browse
                </span>
                <span className="text-xs text-gray-400">Supports ZIP, JSON, CSV, TXT</span>
                <input
                  type="file"
                  accept=".zip,.json,.csv,.txt,.jsonl"
                  className="hidden"
                  onChange={handleArchiveUpload}
                />
                {importMutation.isPending && (
                  <span className="text-sm font-medium text-sky-600">Analyzing transcripts...</span>
                )}
              </label>
            )}

            {transcriptReport && (
              <div className="space-y-4">
                {/* Insights Summary */}
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <InsightCard label="Conversations" value={transcriptReport.conversation_count} />
                  <InsightCard label="Languages" value={transcriptReport.languages.join(', ')} />
                  <InsightCard label="Insights" value={transcriptReport.insights.length} />
                  <InsightCard label="Missing Intents" value={transcriptReport.missing_intents.length} />
                </div>

                {/* Intent Distribution */}
                {transcriptReport.insights.length > 0 && (
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">
                      Top Insights
                    </p>
                    <div className="space-y-2">
                      {transcriptReport.insights.slice(0, 4).map((insight) => (
                        <div
                          key={insight.insight_id}
                          className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2"
                        >
                          <span className="text-sm text-gray-700">{insight.title}</span>
                          <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700">
                            {(insight.share * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* FAQs */}
                {transcriptReport.faq_entries.length > 0 && (
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">
                      Extracted FAQs
                    </p>
                    <div className="space-y-2">
                      {transcriptReport.faq_entries.slice(0, 3).map((faq) => (
                        <div
                          key={`${faq.intent}-${faq.question}`}
                          className="rounded-lg border border-gray-200 bg-white px-3 py-2"
                        >
                          <p className="text-sm font-medium text-gray-900">{faq.question}</p>
                          <p className="mt-1 text-sm text-gray-500">{faq.answer}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <button
                  onClick={handleGenerateFromTranscript}
                  disabled={generateMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:opacity-60"
                >
                  <Zap className="h-4 w-4" />
                  {generateMutation.isPending
                    ? 'Generating...'
                    : 'Generate Agent from These Transcripts'}
                </button>
              </div>
            )}
          </section>
        )}
      </div>
    );
  }

  // ── Render: Refine Phase ────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      <PageHeader
        title="Intelligence Studio"
        description={agentConfig ? `Refining: ${agentConfig.metadata.agent_name}` : 'Refine your agent'}
        actions={
          <button
            onClick={() => {
              setPhase('input');
              setAgentConfig(null);
              setMessages([]);
              setTranscriptReport(null);
            }}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition hover:bg-gray-50"
          >
            Start Over
          </button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]" style={{ minHeight: 'calc(100vh - 200px)' }}>
        {/* Left Panel: Chat */}
        <section className="flex flex-col rounded-2xl border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center gap-2 border-b border-gray-100 px-5 py-3">
            <MessageSquare className="h-4 w-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">Conversational Refinement</h3>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4" style={{ maxHeight: 'calc(100vh - 360px)' }}>
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-gray-900 text-white'
                      : 'border border-gray-200 bg-gray-50 text-gray-700'
                  }`}
                >
                  {msg.content.split('\n').map((line, i) => (
                    <p key={`${msg.id}-${i}`} className={i > 0 ? 'mt-2' : ''}>
                      {line.startsWith('- ') ? (
                        <span className="flex gap-2">
                          <span className="text-gray-400">•</span>
                          <span>{line.slice(2)}</span>
                        </span>
                      ) : line.startsWith('**') && line.endsWith('**') ? (
                        <strong className="font-semibold">{line.slice(2, -2)}</strong>
                      ) : (
                        renderInlineBold(line)
                      )}
                    </p>
                  ))}
                </div>
              </div>
            ))}
            {chatMutation.isPending && (
              <div className="flex justify-start">
                <div className="rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-500">
                  Updating config...
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Composer */}
          <div className="border-t border-gray-100 px-5 py-3">
            <div className="flex gap-2">
              <input
                value={composer}
                onChange={(e) => setComposer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleChatSend();
                  }
                }}
                className="flex-1 rounded-xl border border-gray-300 px-4 py-2.5 text-sm text-gray-800 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
                placeholder="Add escalation logic, refund handling, safety policies..."
                disabled={chatMutation.isPending}
              />
              <button
                onClick={handleChatSend}
                disabled={chatMutation.isPending || !composer.trim()}
                className="rounded-xl bg-gray-900 px-4 py-2.5 text-white transition hover:bg-gray-800 disabled:opacity-60"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>

        {/* Right Panel: Live Agent Preview */}
        <section className="flex flex-col rounded-2xl border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
            <div className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-gray-500" />
              <h3 className="text-sm font-semibold text-gray-900">Agent Config</h3>
            </div>
            <div className="flex gap-1">
              <button
                onClick={handleCopyConfig}
                className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
                title="Copy YAML"
              >
                <Copy className="h-4 w-4" />
              </button>
              <button
                onClick={handleExportConfig}
                className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
                title="Download YAML"
              >
                <Download className="h-4 w-4" />
              </button>
            </div>
          </div>

          {agentConfig && (
            <div className="flex-1 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 360px)' }}>
              {/* Stats Bar */}
              <div className="grid grid-cols-3 gap-px border-b border-gray-100 bg-gray-100">
                <StatCell label="Tools" value={agentConfig.tools.length} />
                <StatCell label="Policies" value={agentConfig.policies.length} />
                <StatCell label="Routing Rules" value={agentConfig.routing_rules.length} />
              </div>

              {/* Collapsible Sections */}
              <div className="divide-y divide-gray-100">
                <ConfigSection
                  title="System Prompt"
                  sectionKey="system_prompt"
                  expanded={expandedSection === 'system_prompt'}
                  onToggle={toggleSection}
                >
                  <pre className="whitespace-pre-wrap text-xs leading-relaxed text-gray-700 font-mono bg-gray-50 rounded-lg p-3">
                    {agentConfig.system_prompt}
                  </pre>
                </ConfigSection>

                <ConfigSection
                  title={`Tools (${agentConfig.tools.length})`}
                  sectionKey="tools"
                  expanded={expandedSection === 'tools'}
                  onToggle={toggleSection}
                >
                  <div className="space-y-2">
                    {agentConfig.tools.map((tool) => (
                      <div key={tool.name} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                        <p className="text-xs font-semibold text-gray-900">{tool.name}</p>
                        <p className="mt-0.5 text-xs text-gray-500">{tool.description}</p>
                        {tool.parameters.length > 0 && (
                          <p className="mt-1 text-xs text-gray-400">
                            Params: {tool.parameters.join(', ')}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </ConfigSection>

                <ConfigSection
                  title={`Routing Rules (${agentConfig.routing_rules.length})`}
                  sectionKey="routing_rules"
                  expanded={expandedSection === 'routing_rules'}
                  onToggle={toggleSection}
                >
                  <div className="space-y-2">
                    {agentConfig.routing_rules.map((rule, i) => (
                      <div key={`rule-${i}`} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-semibold text-gray-900">{rule.action}</p>
                          <span className="rounded-full bg-white px-2 py-0.5 text-xs text-gray-500">
                            P{rule.priority}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-gray-500">When: {rule.condition}</p>
                      </div>
                    ))}
                  </div>
                </ConfigSection>

                <ConfigSection
                  title={`Policies (${agentConfig.policies.length})`}
                  sectionKey="policies"
                  expanded={expandedSection === 'policies'}
                  onToggle={toggleSection}
                >
                  <div className="space-y-2">
                    {agentConfig.policies.map((policy) => (
                      <div key={policy.name} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-semibold text-gray-900">{policy.name}</p>
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                              policy.enforcement === 'strict'
                                ? 'bg-red-50 text-red-600'
                                : 'bg-amber-50 text-amber-600'
                            }`}
                          >
                            {policy.enforcement}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-gray-500">{policy.description}</p>
                      </div>
                    ))}
                  </div>
                </ConfigSection>

                <ConfigSection
                  title={`Eval Criteria (${agentConfig.eval_criteria.length})`}
                  sectionKey="eval_criteria"
                  expanded={expandedSection === 'eval_criteria'}
                  onToggle={toggleSection}
                >
                  <div className="space-y-2">
                    {agentConfig.eval_criteria.map((criterion) => (
                      <div key={criterion.name} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                        <div className="flex items-center justify-between">
                          <p className="text-xs font-semibold text-gray-900">{criterion.name}</p>
                          <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700">
                            {(criterion.weight * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-gray-500">{criterion.description}</p>
                      </div>
                    ))}
                  </div>
                </ConfigSection>
              </div>

              {/* Action Buttons */}
              <div className="border-t border-gray-100 p-4 space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => navigate('/evals?new=1')}
                    className="flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
                  >
                    <Play className="h-3.5 w-3.5" />
                    Generate Evals
                  </button>
                  <button
                    onClick={handleExportConfig}
                    className="flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export Config
                  </button>
                  <button
                    onClick={() => navigate('/evals?run=1')}
                    className="flex items-center justify-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Run First Eval
                  </button>
                  <button
                    onClick={() => navigate('/optimize?new=1')}
                    className="flex items-center justify-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100"
                  >
                    <Zap className="h-3.5 w-3.5" />
                    Start Optimization
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function InsightCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white px-4 py-2.5 text-center">
      <p className="text-lg font-semibold text-gray-900">{value}</p>
      <p className="text-[11px] font-medium text-gray-400">{label}</p>
    </div>
  );
}

function ConfigSection({
  title,
  sectionKey,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  sectionKey: string;
  expanded: boolean;
  onToggle: (key: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        onClick={() => onToggle(sectionKey)}
        className="flex w-full items-center justify-between px-5 py-3 text-left transition hover:bg-gray-50"
      >
        <span className="text-sm font-semibold text-gray-900">{title}</span>
        <ChevronDown
          className={`h-4 w-4 text-gray-400 transition ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

function renderInlineBold(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}
