import {
  startTransition,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  Archive,
  Brain,
  Code2,
  Copy,
  Download,
  FileText,
  FolderOpen,
  ListTree,
  MessageSquare,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  WandSparkles,
} from 'lucide-react';
import {
  useBuilderArtifacts,
  useChatRefine,
  useGenerateAgent,
  useImportTranscriptArchive,
  useSavedBuildArtifacts,
  useTranscriptReports,
} from '../lib/api';
import {
  exportBuilderConfig,
  sendBuilderMessage,
  type BuilderConfig,
  type BuilderSessionPayload,
} from '../lib/builder-chat-api';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import type {
  BuildArtifact,
  BuildArtifactSource,
  GeneratedAgentConfig,
  TranscriptReport,
  TranscriptReportSummary,
} from '../lib/types';
import type { ArtifactRef } from '../lib/builder-types';
import { classNames } from '../lib/utils';

type BuildTab = 'prompt' | 'transcript' | 'builder-chat' | 'saved-artifacts';
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

type InstructionStudioMode = 'raw' | 'form';

interface InstructionFormState {
  preamble: string;
  role: string;
  primaryGoal: string;
  guidelines: string;
  constraints: string;
  subtaskName: string;
  stepOneName: string;
  stepOneTrigger: string;
  stepOneAction: string;
  stepTwoName: string;
  stepTwoTrigger: string;
  stepTwoAction: string;
  examples: string;
}

interface InstructionValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  form: InstructionFormState;
}

const BUILD_ARTIFACT_STORAGE_KEY = 'autoagent.build-artifacts.v1';

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

const BUILDER_PROMPTS = [
  'Build me a customer support agent for an airline that handles booking changes, cancellations, and flight status',
  'Add a tool for checking flight status',
  'Make it more empathetic',
  'Add a policy that it should never reveal internal codes',
];

const DEFAULT_INSTRUCTION_FORM: InstructionFormState = {
  preamble: 'CURRENT CHANNEL: web chat',
  role: 'Customer support router.',
  primaryGoal: 'Route customer requests to the right specialist and keep the response safe and concise.',
  guidelines: 'Keep the tone calm and practical.\nAsk one clarifying question when a required detail is missing.',
  constraints:
    'Protect customer privacy and never expose another customer\'s data.\nRefuse unsafe or policy-violating requests politely.',
  subtaskName: 'Routing',
  stepOneName: 'Identify Intent',
  stepOneTrigger: 'A customer asks for help.',
  stepOneAction: 'Identify whether the request is about support, orders, or recommendations.',
  stepTwoName: 'Clarify Missing Details',
  stepTwoTrigger: 'The request is ambiguous or lacks a required detail.',
  stepTwoAction: 'Ask one focused clarifying question before answering or routing.',
  examples:
    'EXAMPLE 1:\nBegin example\n[user]\nWhere is my order #1001?\n[model]\nI can help with that. I\'ll route this to the order specialist so we can check the latest shipping status.\nEnd example',
};

const WEATHER_ROUTING_GUIDE_XML = `CURRENT CUSTOMER: {username}

<role>The main Weather Agent coordinating multiple agents.</role>
<persona>
  <primary_goal>To provide weather information.</primary_goal>
  Follow the constraints and task flow precisely.
</persona>
<constraints>
  1. Use {@TOOL: get_weather} only for specific weather requests.
  2. If the user's name is known, greet them by name.
</constraints>
<taskflow>
  <subtask name="Query Analysis and Routing">
    <step name="Analyze User Query">
      <trigger>User provides a query.</trigger>
      <action>Determine whether the query is a greeting, farewell, weather request, or something else.</action>
    </step>
    <step name="Handle Weather Request">
      <trigger>User query is identified as a specific weather request.</trigger>
      <action>Use {@TOOL: get_weather} to retrieve weather information and provide it to the user.</action>
    </step>
  </subtask>
</taskflow>
<examples>
  EXAMPLE 1:
  Begin example
  [user]
  What's the weather in London?
  [model]
  The weather in London is 15 C and Cloudy.
  End example
</examples>`;

const XML_GUIDE_LIBRARY = [
  {
    label: 'Weather Routing Guide',
    description: 'Adapted from the Google XML structure example.',
    xml: WEATHER_ROUTING_GUIDE_XML,
  },
  {
    label: 'Support Skeleton',
    description: 'A practical starter layout for customer support agents.',
    xml: buildInstructionXmlFromForm(DEFAULT_INSTRUCTION_FORM),
  },
  {
    label: 'Few-Shot Block',
    description: 'Drop in a compact example block when instructions alone are not enough.',
    xml: `${buildInstructionXmlFromForm(DEFAULT_INSTRUCTION_FORM)}

<!-- Add examples sparingly and only for stubborn behavior gaps. -->`,
  },
];

/**
 * Unified build workspace that combines prompt-led studio, transcript-led studio, builder chat,
 * and saved artifacts in one tabbed surface.
 */
export function Build() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [savedArtifacts, setSavedArtifacts] = useState<BuildArtifact[]>(loadStoredBuildArtifacts);
  const activeTab = parseBuildTab(searchParams.get('tab')) ?? 'prompt';

  useEffect(() => {
    try {
      window.localStorage.setItem(BUILD_ARTIFACT_STORAGE_KEY, JSON.stringify(savedArtifacts));
    } catch {
      // Persistence should not block the build workspace.
    }
  }, [savedArtifacts]);

  function handleArtifactCreated(artifact: BuildArtifact) {
    setSavedArtifacts((current) => upsertBuildArtifact(current, artifact));
  }

  function handleTabChange(nextTab: BuildTab) {
    const nextSearchParams = new URLSearchParams(searchParams);
    if (nextTab === 'prompt') {
      nextSearchParams.delete('tab');
    } else {
      nextSearchParams.set('tab', nextTab);
    }
    setSearchParams(nextSearchParams, { replace: true });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Build"
        description="Prompt, transcript, builder chat, and saved artifacts in one workspace."
      />

      <BuildTabBar activeTab={activeTab} onChange={handleTabChange} />

      <div className="space-y-6">
        <BuildTabPanel id="prompt-panel" active={activeTab === 'prompt'}>
          <StudioWorkspace
            showHeader={false}
            showModeToggle={false}
            fixedMode="prompt"
            onArtifactCreated={handleArtifactCreated}
          />
        </BuildTabPanel>

        <BuildTabPanel id="transcript-panel" active={activeTab === 'transcript'}>
          <StudioWorkspace
            showHeader={false}
            showModeToggle={false}
            fixedMode="transcript"
            onArtifactCreated={handleArtifactCreated}
          />
        </BuildTabPanel>

        <BuildTabPanel id="builder-chat-panel" active={activeTab === 'builder-chat'}>
          <BuilderChatWorkspace showHeader={false} onArtifactCreated={handleArtifactCreated} />
        </BuildTabPanel>

        <BuildTabPanel id="saved-artifacts-panel" active={activeTab === 'saved-artifacts'}>
          <SavedArtifactsWorkspace
            active={activeTab === 'saved-artifacts'}
            localArtifacts={savedArtifacts}
          />
        </BuildTabPanel>
      </div>
    </div>
  );
}

export function BuilderChatWorkspace({
  showHeader = true,
  onArtifactCreated,
}: {
  showHeader?: boolean;
  onArtifactCreated?: (artifact: BuildArtifact) => void;
}) {
  const [composer, setComposer] = useState('');
  const [session, setSession] = useState<BuilderSessionPayload | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const artifactCreatedAtRef = useRef<string | null>(null);

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
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Builder request failed');
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

      const createdAt = artifactCreatedAtRef.current ?? new Date().toISOString();
      artifactCreatedAtRef.current = createdAt;

      onArtifactCreated?.({
        artifact_id: session.session_id,
        title: session.config.agent_name,
        summary: `Builder chat export for ${session.config.agent_name}`,
        source: 'builder_chat',
        status: 'exported',
        created_at: createdAt,
        updated_at: new Date().toISOString(),
        config_yaml: payload.content,
        builder_session_id: session.session_id,
      });
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : 'Config export failed');
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

  const body = (
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
            {BUILDER_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
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
  );

  if (!showHeader) {
    return body;
  }

  return (
    <div data-testid="builder-page" className="space-y-6">
      <PageHeader
        title="Builder"
        description="Describe the agent you want to build, refine it in conversation, and watch the config update live."
      />
      {body}
    </div>
  );
}

export function StudioWorkspace({
  showHeader = true,
  showModeToggle = true,
  fixedMode,
  onArtifactCreated,
}: {
  showHeader?: boolean;
  showModeToggle?: boolean;
  fixedMode?: StudioMode;
  onArtifactCreated?: (artifact: BuildArtifact) => void;
}) {
  const navigate = useNavigate();
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const artifactIdRef = useRef<string | null>(null);
  const artifactCreatedAtRef = useRef<string | null>(null);

  const [mode, setMode] = useState<StudioMode>(fixedMode ?? 'prompt');
  const [phase, setPhase] = useState<StudioPhase>('setup');
  const [prompt, setPrompt] = useState('');
  const [transcriptReport, setTranscriptReport] = useState<TranscriptReport | null>(null);
  const [agentConfig, setAgentConfig] = useState<GeneratedAgentConfig | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [composer, setComposer] = useState('');
  const [instructionMode, setInstructionMode] = useState<InstructionStudioMode>('raw');
  const [instructionXml, setInstructionXml] = useState(() => buildInstructionXmlFromForm(DEFAULT_INSTRUCTION_FORM));

  const importMutation = useImportTranscriptArchive();
  const generateMutation = useGenerateAgent();
  const refineMutation = useChatRefine();

  useEffect(() => {
    if (typeof chatEndRef.current?.scrollIntoView === 'function') {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const currentMode = fixedMode ?? mode;
  const yamlPreview = agentConfig ? configToYaml(agentConfig) : '';
  const transcriptIntents = transcriptReport ? buildIntentSummaries(transcriptReport) : [];
  const patternSignals = transcriptReport ? buildPatternSignals(transcriptReport) : [];

  function persistArtifact(
    source: BuildArtifactSource,
    title: string,
    summary: string,
    configYaml: string,
    options?: {
      promptUsed?: string;
      transcriptReportId?: string;
      builderSessionId?: string;
      status?: BuildArtifact['status'];
    }
  ) {
    const artifactId = artifactIdRef.current ?? crypto.randomUUID();
    artifactIdRef.current = artifactId;
    const createdAt = artifactCreatedAtRef.current ?? new Date().toISOString();
    artifactCreatedAtRef.current = createdAt;
    onArtifactCreated?.({
      artifact_id: artifactId,
      title,
      summary,
      source,
      status: options?.status ?? 'complete',
      created_at: createdAt,
      updated_at: new Date().toISOString(),
      config_yaml: configYaml,
      prompt_used: options?.promptUsed,
      transcript_report_id: options?.transcriptReportId,
      builder_session_id: options?.builderSessionId,
    });
  }

  function resetStudio() {
    setPhase('setup');
    setPrompt('');
    setTranscriptReport(null);
    setAgentConfig(null);
    setMessages([]);
    setComposer('');
    setInstructionMode('raw');
    setInstructionXml(buildInstructionXmlFromForm(DEFAULT_INSTRUCTION_FORM));
    artifactIdRef.current = null;
    artifactCreatedAtRef.current = null;

    if (!fixedMode) {
      setMode('prompt');
    }
  }

  function handlePromptGenerate() {
    const nextPrompt = prompt.trim();
    if (!nextPrompt) {
      toastError('Prompt required', 'Describe the agent you want to build.');
      return;
    }

    const instructionValidation = validateInstructionXmlDraft(instructionXml);
    if (!instructionValidation.valid) {
      toastError(
        'Instruction XML invalid',
        instructionValidation.errors[0] ?? 'Fix the XML draft before generating the agent.'
      );
      return;
    }

    const generationPrompt = `${nextPrompt}\n\nDefault XML instruction draft:\n${instructionXml}`;

    generateMutation.mutate(
      { prompt: generationPrompt },
      {
        onSuccess: (config) => {
          artifactIdRef.current = null;
          const configYaml = configToYaml(config);
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            buildAssistantMessage(
              `I drafted **${config.metadata.agent_name}** with ${config.tools.length} tools, ${config.routing_rules.length} routing rules, and ${config.policies.length} policies. Tell me what to refine next.`
            ),
          ]);
          persistArtifact(
            'prompt',
            config.metadata.agent_name,
            'Generated from a prompt',
            configYaml,
            { promptUsed: generationPrompt }
          );
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

    const instructionValidation = validateInstructionXmlDraft(instructionXml);
    if (!instructionValidation.valid) {
      toastError(
        'Instruction XML invalid',
        instructionValidation.errors[0] ?? 'Fix the XML draft before generating the agent.'
      );
      return;
    }

    generateMutation.mutate(
      {
        prompt: `Generate an agent from transcript insights in ${transcriptReport.archive_name}\n\nDefault XML instruction draft:\n${instructionXml}`,
        transcript_report_id: transcriptReport.report_id,
      },
      {
        onSuccess: (config) => {
          artifactIdRef.current = null;
          const configYaml = configToYaml(config);
          setAgentConfig(config);
          setPhase('refine');
          setMessages([
            buildAssistantMessage(
              `I turned the transcript analysis into **${config.metadata.agent_name}**. The config already reflects the top intent gaps, workflow signals, and FAQ patterns from the upload.`
            ),
          ]);
          persistArtifact(
            'transcript',
            config.metadata.agent_name,
            `Generated from ${transcriptReport.archive_name}`,
            configYaml,
            {
              transcriptReportId: transcriptReport.report_id,
            }
          );
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
          persistArtifact(
            currentMode,
            result.config.metadata.agent_name,
            currentMode === 'transcript'
              ? `Refined from ${transcriptReport?.archive_name ?? 'transcript analysis'}`
              : 'Refined from a prompt',
            configToYaml(result.config),
            {
              promptUsed: currentMode === 'prompt' ? prompt.trim() : undefined,
              transcriptReportId: transcriptReport?.report_id,
            }
          );
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

    const yaml = configToYaml(agentConfig);
    const blob = new Blob([yaml], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${slugify(agentConfig.metadata.agent_name)}.yaml`;
    link.click();
    URL.revokeObjectURL(url);
    toastSuccess('Config exported', 'Downloaded the YAML config.');

    persistArtifact(currentMode, agentConfig.metadata.agent_name, 'Exported YAML config', yaml, {
      promptUsed: currentMode === 'prompt' ? prompt.trim() : undefined,
      transcriptReportId: transcriptReport?.report_id,
      status: 'exported',
    });
  }

  const setupBody =
    currentMode === 'prompt' ? (
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

          <InstructionStudio
            mode={instructionMode}
            onModeChange={setInstructionMode}
            xml={instructionXml}
            onXmlChange={setInstructionXml}
          />

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-gray-500">
              Start with the job, channels, policies, and any must-have tools or routing rules. The validated XML draft is included when you generate the agent.
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
                        <span className="text-sm font-medium text-gray-800">
                          {humanizeLabel(intent.label)}
                        </span>
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
    );

  const refineBody = (
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
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">Agent</p>
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
  );

  const body = (
    <div className="space-y-4">
      {!showHeader ? null : (
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
      )}

      {phase === 'setup' ? (
        <div className="space-y-6">
          {showModeToggle && !fixedMode ? <StudioModeToggle mode={mode} onChange={setMode} /> : null}
          {setupBody}
        </div>
      ) : (
        refineBody
      )}
    </div>
  );

  return body;
}

export function SavedArtifactsWorkspace({
  localArtifacts,
  active,
}: {
  localArtifacts: BuildArtifact[];
  active: boolean;
}) {
  const savedBuildArtifactsQuery = useSavedBuildArtifacts(active);
  const builderArtifactsQuery = useBuilderArtifacts({ enabled: active });
  const transcriptReportsQuery = useTranscriptReports(active);

  return (
    <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-2 border-b border-gray-100 pb-4">
        <div className="flex items-center gap-2">
          <FolderOpen className="h-4 w-4 text-gray-500" />
          <h3 className="text-base font-semibold text-gray-900">Saved Artifacts</h3>
        </div>
        <p className="text-sm text-gray-500">
          Persisted build artifacts from the UI and API-backed artifact sources.
        </p>
      </div>

      <div className="mt-5 space-y-6">
        <ArtifactSection
          title="Shared Build Artifacts"
          count={savedBuildArtifactsQuery.data?.length ?? 0}
          status={savedBuildArtifactsQuery.isFetching ? 'Loading...' : undefined}
        >
          {savedBuildArtifactsQuery.data && savedBuildArtifactsQuery.data.length > 0 ? (
            <div className="space-y-3">
              {savedBuildArtifactsQuery.data.map((artifact) => (
                <BuildArtifactCard key={`shared-${artifact.artifact_id}`} artifact={artifact} />
              ))}
            </div>
          ) : savedBuildArtifactsQuery.isError ? (
            <EmptyState text="Unable to load shared build artifacts right now." />
          ) : (
            <EmptyState text="Shared CLI and API build artifacts will appear here as they are generated." />
          )}
        </ArtifactSection>

        <ArtifactSection title="Persisted Build Artifacts" count={localArtifacts.length}>
          {localArtifacts.length === 0 ? (
            <EmptyState text="No saved build artifacts yet. Generate or export from any build tab to persist one here." />
          ) : (
            <div className="space-y-3">
              {localArtifacts.map((artifact) => (
                <BuildArtifactCard key={artifact.artifact_id} artifact={artifact} />
              ))}
            </div>
          )}
        </ArtifactSection>

        <ArtifactSection
          title="Builder API Artifacts"
          count={builderArtifactsQuery.data?.length ?? 0}
          status={builderArtifactsQuery.isFetching ? 'Loading...' : undefined}
        >
          {builderArtifactsQuery.data && builderArtifactsQuery.data.length > 0 ? (
            <div className="space-y-3">
              {builderArtifactsQuery.data.map((artifact) => (
                <ApiArtifactCard key={artifact.artifact_id} artifact={artifact} />
              ))}
            </div>
          ) : builderArtifactsQuery.isError ? (
            <EmptyState text="Unable to load API artifacts right now." />
          ) : (
            <EmptyState text="Open this tab after creating builder artifacts to see the server-backed list." />
          )}
        </ArtifactSection>

        <ArtifactSection
          title="Transcript Reports"
          count={transcriptReportsQuery.data?.length ?? 0}
          status={transcriptReportsQuery.isFetching ? 'Loading...' : undefined}
        >
          {transcriptReportsQuery.data && transcriptReportsQuery.data.length > 0 ? (
            <div className="space-y-3">
              {transcriptReportsQuery.data.map((report) => (
                <TranscriptReportCard key={report.report_id} report={report} />
              ))}
            </div>
          ) : transcriptReportsQuery.isError ? (
            <EmptyState text="Unable to load transcript reports right now." />
          ) : (
            <EmptyState text="Transcript reports will appear here after uploads are analyzed." />
          )}
        </ArtifactSection>
      </div>
    </section>
  );
}

function InstructionStudio({
  mode,
  onModeChange,
  xml,
  onXmlChange,
}: {
  mode: InstructionStudioMode;
  onModeChange: (mode: InstructionStudioMode) => void;
  xml: string;
  onXmlChange: (xml: string) => void;
}) {
  const parsed = parseInstructionXmlDraft(xml);
  const [formState, setFormState] = useState<InstructionFormState>(parsed.form);

  useEffect(() => {
    if (parsed.valid) {
      setFormState(parsed.form);
    }
  }, [xml]);

  function handleRawChange(value: string) {
    onXmlChange(value);
    const nextParsed = parseInstructionXmlDraft(value);
    if (nextParsed.valid) {
      setFormState(nextParsed.form);
    }
  }

  function handleFormFieldChange(field: keyof InstructionFormState, value: string) {
    const nextForm = {
      ...formState,
      [field]: value,
    };
    setFormState(nextForm);
    onXmlChange(buildInstructionXmlFromForm(nextForm));
  }

  function handleLibraryInsert(snippet: string) {
    onXmlChange(snippet);
    const nextParsed = parseInstructionXmlDraft(snippet);
    setFormState(nextParsed.form);
  }

  return (
    <section className="overflow-hidden rounded-[28px] border border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.96),rgba(255,255,255,1))] shadow-sm shadow-amber-100/60">
      <div className="border-b border-amber-200 px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-300 bg-white/90 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700">
              <Code2 className="h-3.5 w-3.5" />
              Google XML Default
            </div>
            <h3 className="mt-3 text-lg font-semibold text-gray-900">XML Instruction Studio</h3>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-gray-600">
              Draft the default instruction in the recommended XML shape, switch between raw and form editing, and borrow starter snippets from the guide without leaving the page.
            </p>
          </div>

          <div className="inline-flex rounded-2xl border border-gray-200 bg-white p-1 shadow-sm">
            <button
              type="button"
              aria-pressed={mode === 'raw'}
              onClick={() => onModeChange('raw')}
              className={classNames(
                'rounded-xl px-3 py-2 text-sm font-medium transition',
                mode === 'raw' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              )}
            >
              Raw XML
            </button>
            <button
              type="button"
              aria-pressed={mode === 'form'}
              onClick={() => onModeChange('form')}
              className={classNames(
                'rounded-xl px-3 py-2 text-sm font-medium transition',
                mode === 'form' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
              )}
            >
              Form View
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-5 px-6 py-6">
        <div className="grid gap-3 lg:grid-cols-3">
          {XML_GUIDE_LIBRARY.map((example) => (
            <button
              key={example.label}
              type="button"
              aria-label={example.label}
              onClick={() => handleLibraryInsert(example.xml)}
              className="group rounded-3xl border border-amber-200 bg-white/90 p-4 text-left transition hover:-translate-y-0.5 hover:border-amber-300 hover:shadow-md hover:shadow-amber-100/70"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-gray-900">{example.label}</p>
                <Sparkles className="h-4 w-4 text-amber-500 transition group-hover:rotate-6" />
              </div>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">{example.description}</p>
            </button>
          ))}
        </div>

        {parsed.errors.length > 0 ? (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                {parsed.errors.map((error) => (
                  <p key={error}>{error}</p>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {parsed.warnings.length > 0 ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            <div className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                {parsed.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {mode === 'raw' ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)]">
            <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                    Editor
                  </p>
                  <p className="mt-1 text-sm text-gray-600">
                    Edit the source directly. When the XML is valid, form mode stays in sync automatically.
                  </p>
                </div>
              </div>
              <textarea
                aria-label="XML instruction editor"
                value={xml}
                onChange={(event) => handleRawChange(event.target.value)}
                rows={22}
                spellCheck={false}
                className="min-h-[420px] w-full resize-y rounded-2xl border border-gray-200 bg-[#0F172A] px-4 py-4 font-mono text-[13px] leading-6 text-slate-100 outline-none transition focus:border-amber-400 focus:ring-4 focus:ring-amber-100"
              />
            </div>

            <div className="rounded-3xl border border-gray-200 bg-[#111827] p-4 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-slate-200">
                <ListTree className="h-4 w-4 text-amber-300" />
                <p className="text-sm font-semibold">Syntax Highlight Preview</p>
              </div>
              <pre
                aria-label="XML syntax preview"
                className="max-h-[420px] overflow-auto rounded-2xl border border-white/10 bg-black/30 p-4 font-mono text-[12px] leading-6 text-slate-100"
              >
                {renderHighlightedXml(xml)}
              </pre>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <label className="space-y-2 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <span className="text-sm font-semibold text-gray-900">Instruction role</span>
              <input
                aria-label="Instruction role"
                value={formState.role}
                onChange={(event) => handleFormFieldChange('role', event.target.value)}
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </label>

            <label className="space-y-2 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <span className="text-sm font-semibold text-gray-900">Primary goal</span>
              <input
                aria-label="Primary goal"
                value={formState.primaryGoal}
                onChange={(event) => handleFormFieldChange('primaryGoal', event.target.value)}
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </label>

            <label className="space-y-2 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <span className="text-sm font-semibold text-gray-900">Persona guidance</span>
              <textarea
                value={formState.guidelines}
                onChange={(event) => handleFormFieldChange('guidelines', event.target.value)}
                rows={5}
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </label>

            <label className="space-y-2 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <span className="text-sm font-semibold text-gray-900">Constraints</span>
              <textarea
                value={formState.constraints}
                onChange={(event) => handleFormFieldChange('constraints', event.target.value)}
                rows={5}
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </label>

            <div className="space-y-3 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-gray-900">Taskflow</p>
              <input
                value={formState.subtaskName}
                onChange={(event) => handleFormFieldChange('subtaskName', event.target.value)}
                placeholder="Subtask name"
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
              <input
                value={formState.stepOneName}
                onChange={(event) => handleFormFieldChange('stepOneName', event.target.value)}
                placeholder="Step one name"
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
              <textarea
                value={formState.stepOneTrigger}
                onChange={(event) => handleFormFieldChange('stepOneTrigger', event.target.value)}
                rows={2}
                placeholder="Step one trigger"
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
              <textarea
                value={formState.stepOneAction}
                onChange={(event) => handleFormFieldChange('stepOneAction', event.target.value)}
                rows={2}
                placeholder="Step one action"
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </div>

            <div className="space-y-3 rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-gray-900">Examples</p>
              <textarea
                value={formState.examples}
                onChange={(event) => handleFormFieldChange('examples', event.target.value)}
                rows={12}
                className="w-full rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 font-mono text-[13px] leading-6 text-gray-900 outline-none transition focus:border-amber-400 focus:bg-white focus:ring-4 focus:ring-amber-100"
              />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function BuildTabBar({
  activeTab,
  onChange,
}: {
  activeTab: BuildTab;
  onChange: (tab: BuildTab) => void;
}) {
  const tabs: Array<{ id: BuildTab; label: string; icon: ReactNode }> = [
    { id: 'prompt', label: 'Prompt', icon: <Sparkles className="h-4 w-4" /> },
    { id: 'transcript', label: 'Transcript', icon: <FileText className="h-4 w-4" /> },
    { id: 'builder-chat', label: 'Builder Chat', icon: <MessageSquare className="h-4 w-4" /> },
    { id: 'saved-artifacts', label: 'Saved Artifacts', icon: <Archive className="h-4 w-4" /> },
  ];

  return (
    <div
      role="tablist"
      aria-label="Build sections"
      className="inline-flex flex-wrap gap-2 rounded-2xl border border-gray-200 bg-white p-1 shadow-sm"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          aria-controls={`${tab.id}-panel`}
          onClick={() => onChange(tab.id)}
          className={classNames(
            'inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition',
            activeTab === tab.id
              ? 'bg-gray-900 text-white'
              : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
          )}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function BuildTabPanel({
  id,
  active,
  children,
}: {
  id: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <section id={id} role="tabpanel" hidden={!active} aria-hidden={!active}>
      {children}
    </section>
  );
}

function ArtifactSection({
  title,
  count,
  status,
  children,
}: {
  title: string;
  count: number;
  status?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-gray-50/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <p className="text-xs text-gray-500">{count} item{count === 1 ? '' : 's'}</p>
        </div>
        {status ? <p className="text-xs font-medium text-gray-500">{status}</p> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function BuildArtifactCard({ artifact }: { artifact: BuildArtifact }) {
  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">{artifact.title}</h4>
          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-gray-400">
            {humanizeArtifactSource(artifact.source)} · {artifact.status}
          </p>
        </div>
        <p className="text-xs text-gray-500">Updated {formatTimestamp(artifact.updated_at)}</p>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-gray-600">{artifact.summary}</p>
      <pre className="mt-3 overflow-x-auto rounded-xl bg-gray-950 p-3 text-[11px] leading-5 text-gray-200">
        {artifact.config_yaml}
      </pre>
    </article>
  );
}

function ApiArtifactCard({ artifact }: { artifact: ArtifactRef }) {
  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">{artifact.title}</h4>
          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-gray-400">
            {artifact.artifact_type}
          </p>
        </div>
        <p className="text-xs text-gray-500">Updated {formatTimestamp(artifact.updated_at)}</p>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-gray-600">{artifact.summary}</p>
    </article>
  );
}

function TranscriptReportCard({ report }: { report: TranscriptReportSummary }) {
  return (
    <article className="rounded-2xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">{report.archive_name}</h4>
          <p className="mt-1 text-xs uppercase tracking-[0.18em] text-gray-400">
            {report.conversation_count} conversations
          </p>
        </div>
        <p className="text-xs text-gray-500">Created {formatTimestamp(report.created_at)}</p>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-gray-600">
        Languages: {report.languages.join(', ') || 'n/a'}
      </p>
    </article>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-gray-200 bg-white px-4 py-5 text-sm text-gray-500">
      {text}
    </div>
  );
}

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

function ConfigLine({ line }: { line: string }) {
  const keyMatch = line.match(/^(\s*)"([^"]+)":\s(.*)$/);
  if (!keyMatch) {
    return <div className="whitespace-pre-wrap text-slate-400">{line}</div>;
  }

  const [, indent, key, value] = keyMatch;
  const valueClass =
    value.startsWith('"')
      ? 'text-sky-700'
      : value.startsWith('[') || value.startsWith('{')
        ? 'text-slate-500'
        : 'text-emerald-700';

  return (
    <div className="whitespace-pre-wrap">
      <span className="text-slate-400">{indent}</span>
      <span className="text-rose-600">"{key}"</span>
      <span className="text-slate-400">: </span>
      <span className={valueClass}>{value}</span>
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

function ChatBubble({ message }: { message: ChatMessage }) {
  const assistant = message.role === 'assistant';
  return (
    <div className={classNames('flex', assistant ? 'justify-start' : 'justify-end')}>
      <div
        className={classNames(
          'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          assistant ? 'border border-gray-200 bg-gray-50 text-gray-700' : 'bg-gray-900 text-white'
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
    <div
      className={classNames(
        compact ? 'bg-white px-3 py-3 text-center' : 'rounded-2xl border border-gray-200 bg-white p-4'
      )}
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">{label}</p>
      <p className={classNames('mt-2 font-semibold text-gray-900', compact ? 'text-lg' : 'text-2xl')}>
        {value}
      </p>
    </div>
  );
}

function loadStoredBuildArtifacts(): BuildArtifact[] {
  if (typeof window === 'undefined') {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(BUILD_ARTIFACT_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw) as BuildArtifact[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function parseBuildTab(value: string | null): BuildTab | null {
  if (
    value === 'prompt' ||
    value === 'transcript' ||
    value === 'builder-chat' ||
    value === 'saved-artifacts'
  ) {
    return value;
  }

  return null;
}

function upsertBuildArtifact(current: BuildArtifact[], next: BuildArtifact): BuildArtifact[] {
  const filtered = current.filter((artifact) => artifact.artifact_id !== next.artifact_id);
  return [next, ...filtered];
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

function humanizeArtifactSource(source: BuildArtifactSource): string {
  return source.replaceAll('_', ' ');
}

function formatTimestamp(value: string | number): string {
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown time' : date.toLocaleString();
}

function buildInstructionXmlFromForm(form: InstructionFormState): string {
  const guidelines = splitInstructionLines(form.guidelines);
  const constraints = splitInstructionLines(form.constraints);
  const examples = splitInstructionExamples(form.examples);
  const preamble = form.preamble.trim();
  const lines: string[] = [];

  if (preamble) {
    lines.push(preamble, '');
  }

  lines.push(`<role>${escapeInstructionXml(form.role.trim())}</role>`);
  lines.push('<persona>');
  lines.push(`  <primary_goal>${escapeInstructionXml(form.primaryGoal.trim())}</primary_goal>`);
  for (const line of guidelines) {
    lines.push(`  ${escapeInstructionXml(line)}`);
  }
  lines.push('</persona>');
  lines.push('<constraints>');
  for (const [index, line] of constraints.entries()) {
    lines.push(`  ${index + 1}. ${escapeInstructionXml(line)}`);
  }
  lines.push('</constraints>');
  lines.push('<taskflow>');
  lines.push(`  <subtask name="${escapeInstructionXml(form.subtaskName.trim())}">`);
  lines.push(`    <step name="${escapeInstructionXml(form.stepOneName.trim())}">`);
  lines.push(`      <trigger>${escapeInstructionXml(form.stepOneTrigger.trim())}</trigger>`);
  lines.push(`      <action>${escapeInstructionXml(form.stepOneAction.trim())}</action>`);
  lines.push('    </step>');

  if (form.stepTwoName.trim() || form.stepTwoTrigger.trim() || form.stepTwoAction.trim()) {
    lines.push(`    <step name="${escapeInstructionXml(form.stepTwoName.trim())}">`);
    lines.push(`      <trigger>${escapeInstructionXml(form.stepTwoTrigger.trim())}</trigger>`);
    lines.push(`      <action>${escapeInstructionXml(form.stepTwoAction.trim())}</action>`);
    lines.push('    </step>');
  }

  lines.push('  </subtask>');
  lines.push('</taskflow>');
  lines.push('<examples>');
  for (const example of examples) {
    for (const line of example.split('\n')) {
      lines.push(`  ${line}`);
    }
  }
  lines.push('</examples>');
  return lines.join('\n');
}

function validateInstructionXmlDraft(xml: string): InstructionValidationResult {
  return parseInstructionXmlDraft(xml);
}

function parseInstructionXmlDraft(xml: string): InstructionValidationResult {
  const fallbackForm = {
    ...DEFAULT_INSTRUCTION_FORM,
  };

  if (!xml.trim()) {
    return {
      valid: false,
      errors: ['XML parse error: the instruction draft is empty.'],
      warnings: [],
      form: fallbackForm,
    };
  }

  const parser = new DOMParser();
  const document = parser.parseFromString(`<instruction>${xml}</instruction>`, 'application/xml');
  const parserError = document.querySelector('parsererror');
  if (parserError) {
    return {
      valid: false,
      errors: [`XML parse error: ${parserError.textContent?.trim() ?? 'Unable to parse XML.'}`],
      warnings: [],
      form: fallbackForm,
    };
  }

  const root = document.documentElement;
  const roleNode = findDirectChild(root, 'role');
  const personaNode = findDirectChild(root, 'persona');
  const primaryGoalNode = personaNode ? findDirectChild(personaNode, 'primary_goal') : null;
  const constraintsNode = findDirectChild(root, 'constraints');
  const taskflowNode = findDirectChild(root, 'taskflow');
  const examplesNode = findDirectChild(root, 'examples');
  const firstSubtask = taskflowNode ? findDirectChild(taskflowNode, 'subtask') : null;
  const steps = firstSubtask
    ? Array.from(firstSubtask.children).filter((child) => child.tagName === 'step')
    : [];
  const firstStep = steps[0] ?? null;
  const secondStep = steps[1] ?? null;

  const errors: string[] = [];
  if (!roleNode?.textContent?.trim()) {
    errors.push('Missing required <role> section.');
  }
  if (!primaryGoalNode?.textContent?.trim()) {
    errors.push('Missing required <persona><primary_goal> section.');
  }
  if (!constraintsNode?.textContent?.trim()) {
    errors.push('Missing required <constraints> section.');
  }
  if (!firstSubtask || !firstStep) {
    errors.push('Missing required <taskflow> with at least one <subtask> and <step>.');
  }

  const warnings: string[] = [];
  if (!examplesNode?.textContent?.trim()) {
    warnings.push('Add examples only when they solve a specific behavior gap.');
  }

  const personaGuidelines = personaNode
    ? Array.from(personaNode.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent?.trim() ?? '')
        .filter(Boolean)
        .join('\n')
    : fallbackForm.guidelines;

  const form: InstructionFormState = {
    preamble: root.firstChild?.nodeType === Node.TEXT_NODE ? root.firstChild.textContent?.trim() ?? '' : '',
    role: roleNode?.textContent?.trim() ?? fallbackForm.role,
    primaryGoal: primaryGoalNode?.textContent?.trim() ?? fallbackForm.primaryGoal,
    guidelines: personaGuidelines || fallbackForm.guidelines,
    constraints: normalizeInstructionListText(constraintsNode?.textContent ?? ''),
    subtaskName: firstSubtask?.getAttribute('name')?.trim() || fallbackForm.subtaskName,
    stepOneName: firstStep?.getAttribute('name')?.trim() || fallbackForm.stepOneName,
    stepOneTrigger:
      findDirectChild(firstStep, 'trigger')?.textContent?.trim() || fallbackForm.stepOneTrigger,
    stepOneAction:
      findDirectChild(firstStep, 'action')?.textContent?.trim() || fallbackForm.stepOneAction,
    stepTwoName: secondStep?.getAttribute('name')?.trim() || fallbackForm.stepTwoName,
    stepTwoTrigger:
      findDirectChild(secondStep, 'trigger')?.textContent?.trim() || fallbackForm.stepTwoTrigger,
    stepTwoAction:
      findDirectChild(secondStep, 'action')?.textContent?.trim() || fallbackForm.stepTwoAction,
    examples: (examplesNode?.textContent ?? '').trim() || fallbackForm.examples,
  };

  return {
    valid: errors.length === 0,
    errors,
    warnings,
    form,
  };
}

function findDirectChild(node: Element | null, tagName: string): Element | null {
  if (!node) {
    return null;
  }
  return Array.from(node.children).find((child) => child.tagName === tagName) ?? null;
}

function splitInstructionLines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)])\s*/, '').trim())
    .filter(Boolean);
}

function splitInstructionExamples(value: string): string[] {
  const normalized = value.trim();
  if (!normalized) {
    return [];
  }
  return normalized
    .split(/\n(?=EXAMPLE\s+\d+:)/g)
    .map((example) => example.trim())
    .filter(Boolean);
}

function normalizeInstructionListText(value: string): string {
  return value
    .split('\n')
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)])\s*/, '').trim())
    .filter(Boolean)
    .join('\n');
}

function escapeInstructionXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function renderHighlightedXml(xml: string): ReactNode[] {
  return xml.split('\n').map((line, lineIndex) => (
    <span key={`xml-line-${lineIndex}`} className="block">
      {line.split(/(<[^>]+>)/g).map((segment, segmentIndex) => {
        if (!segment) {
          return null;
        }
        const key = `xml-segment-${lineIndex}-${segmentIndex}`;
        if (segment.startsWith('<') && segment.endsWith('>')) {
          return (
            <span key={key} className="text-amber-300">
              {segment}
            </span>
          );
        }
        return (
          <span key={key} className="text-slate-200">
            {segment}
          </span>
        );
      })}
    </span>
  ));
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
