import { useEffect, useState, type ChangeEvent, type ReactNode } from 'react';
import { Brain, FileArchive, MessageSquareText, Sparkles, UploadCloud, WandSparkles } from 'lucide-react';
import {
  useApplyTranscriptInsight,
  useAskTranscriptReport,
  useBuildAgentArtifact,
  useImportTranscriptArchive,
  useTranscriptReport,
  useTranscriptReports,
} from '../lib/api';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import type { IntelligenceAnswer, PromptBuildArtifact, TranscriptReport } from '../lib/types';
import { formatPercent, formatTimestamp } from '../lib/utils';

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

const starterQuestions = [
  'Why are people transferring to live support?',
  'What should I change to improve this metric?',
];

const connectorOptions = ['Shopify', 'Amazon Connect', 'Salesforce', 'Zendesk'];

function SummaryCard({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'accent';
}) {
  return (
    <div
      className={
        tone === 'accent'
          ? 'rounded-2xl border border-sky-200 bg-gradient-to-br from-sky-50 to-cyan-50 p-4'
          : 'rounded-2xl border border-gray-200 bg-white p-4'
      }
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-gray-900">{value}</p>
    </div>
  );
}

function ListPanel({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/60">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">{eyebrow}</p>
      <h3 className="mt-2 text-lg font-semibold tracking-tight text-gray-900">{title}</h3>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ReportHighlights({
  report,
  onApplyInsight,
  applyPending,
}: {
  report: TranscriptReport;
  onApplyInsight: (insightId: string) => void;
  applyPending: boolean;
}) {
  return (
    <div className="space-y-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Archive Conversations" value={report.conversation_count} tone="accent" />
        <SummaryCard label="Languages" value={report.languages.join(', ')} />
        <SummaryCard label="Insights" value={report.insights.length} />
        <SummaryCard label="Missing Intents" value={report.missing_intents.length} />
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
        <ListPanel title="Root-Cause Insights" eyebrow="Research">
          <div className="space-y-3">
            {report.insights.map((insight) => (
              <div key={insight.insight_id} className="rounded-2xl border border-sky-100 bg-sky-50/70 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{insight.title}</p>
                    <p className="mt-1 text-sm text-slate-600">{insight.summary}</p>
                  </div>
                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-sky-700">
                    {formatPercent(insight.share)}
                  </span>
                </div>
                <p className="mt-3 text-xs uppercase tracking-[0.16em] text-slate-400">Recommended change</p>
                <p className="mt-1 text-sm text-slate-700">{insight.recommendation}</p>
                {insight.evidence.length > 0 && (
                  <div className="mt-3 rounded-2xl bg-white/80 p-3">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-400">Evidence</p>
                    <ul className="mt-2 space-y-1.5 text-sm text-slate-600">
                      {insight.evidence.map((item) => (
                        <li key={`${insight.insight_id}-${item}`}>“{item}”</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    onClick={() => onApplyInsight(insight.insight_id)}
                    disabled={applyPending}
                    className="rounded-full bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
                  >
                    {applyPending ? 'Drafting...' : 'Apply Insight To Agent'}
                  </button>
                  <span className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                    {insight.drafted_change_prompt}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </ListPanel>

        <div className="space-y-5">
          <ListPanel title="Missing Intents" eyebrow="Coverage">
            <div className="space-y-3">
              {report.missing_intents.map((intent) => (
                <div key={intent.intent} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">{intent.intent.replaceAll('_', ' ')}</p>
                    <span className="rounded-full bg-white px-2 py-1 text-xs font-medium text-gray-600">{intent.count}</span>
                  </div>
                  <p className="mt-2 text-sm text-gray-600">{intent.reason}</p>
                </div>
              ))}
            </div>
          </ListPanel>

          <ListPanel title="Workflow Suggestions" eyebrow="Operationalize">
            <div className="space-y-3">
              {report.workflow_suggestions.map((item) => (
                <div key={item.title} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <p className="text-sm font-semibold text-gray-900">{item.title}</p>
                  <p className="mt-1 text-sm text-gray-600">{item.description}</p>
                </div>
              ))}
            </div>
          </ListPanel>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <ListPanel title="FAQ / Knowledge Base Seeds" eyebrow="Knowledge">
          <div className="space-y-3">
            {report.faq_entries.map((entry) => (
              <div key={`${entry.intent}-${entry.question}`} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-xs uppercase tracking-[0.16em] text-gray-400">{entry.intent.replaceAll('_', ' ')}</p>
                <p className="mt-2 text-sm font-medium text-gray-900">{entry.question}</p>
                <p className="mt-2 text-sm text-gray-600">{entry.answer}</p>
              </div>
            ))}
          </div>
        </ListPanel>

        <ListPanel title="Suggested Regression Tests" eyebrow="Quality">
          <div className="space-y-3">
            {report.suggested_tests.map((test) => (
              <div key={test.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{test.name}</p>
                <p className="mt-2 text-sm text-gray-600">Prompt: {test.user_message}</p>
                <p className="mt-1 text-sm text-gray-600">Expected: {test.expected_behavior}</p>
              </div>
            ))}
          </div>
        </ListPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <ListPanel title="Procedure Extraction" eyebrow="Procedures">
          <div className="space-y-3">
            {report.procedure_summaries.map((procedure) => (
              <div key={`${procedure.intent}-${procedure.source_conversation_id}`} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{procedure.intent.replaceAll('_', ' ')}</p>
                <ol className="mt-3 space-y-1 text-sm text-gray-600">
                  {procedure.steps.map((step, index) => (
                    <li key={`${procedure.source_conversation_id}-${index}`}>{index + 1}. {step}</li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </ListPanel>

        <ListPanel title="Conversation Corpus Samples" eyebrow="Corpus">
          <div className="space-y-3">
            {report.conversations.slice(0, 4).map((conversation) => (
              <div key={conversation.conversation_id} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs uppercase tracking-[0.16em] text-gray-400">
                    {conversation.language} · {conversation.intent.replaceAll('_', ' ')}
                  </p>
                  <span className="rounded-full bg-white px-2 py-1 text-xs font-medium text-gray-600">{conversation.outcome}</span>
                </div>
                <p className="mt-2 text-sm font-medium text-gray-900">{conversation.user_message}</p>
                <p className="mt-2 text-sm text-gray-600">{conversation.agent_response}</p>
              </div>
            ))}
          </div>
        </ListPanel>
      </div>
    </div>
  );
}

function BuilderResult({ artifact }: { artifact: PromptBuildArtifact }) {
  return (
    <div className="space-y-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard label="Connectors" value={artifact.connectors.join(', ') || 'None'} tone="accent" />
        <SummaryCard label="Intents" value={artifact.intents.length} />
        <SummaryCard label="Tools" value={artifact.tools.length} />
        <SummaryCard label="Guardrails" value={artifact.guardrails.length} />
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <ListPanel title="Intent Spec" eyebrow="Builder">
          <div className="space-y-3">
            {artifact.intents.map((intent) => (
              <div key={intent.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{intent.name.replaceAll('_', ' ')}</p>
                <p className="mt-1 text-sm text-gray-600">{intent.description}</p>
              </div>
            ))}
          </div>
        </ListPanel>

        <ListPanel title="Connector Tools" eyebrow="Execution">
          <div className="space-y-3">
            {artifact.tools.map((tool) => (
              <div key={tool.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{tool.name}</p>
                <p className="mt-1 text-sm text-gray-600">{tool.connector} · {tool.purpose}</p>
              </div>
            ))}
          </div>
        </ListPanel>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <ListPanel title="Business Rules & Guardrails" eyebrow="Policy">
          <div className="space-y-3 text-sm text-gray-600">
            {artifact.business_rules.map((rule) => (
              <div key={rule} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">{rule}</div>
            ))}
            {artifact.guardrails.map((rule) => (
              <div key={rule} className="rounded-2xl border border-sky-100 bg-sky-50/70 p-3 text-slate-700">{rule}</div>
            ))}
          </div>
        </ListPanel>

        <ListPanel title="Auth & Escalation" eyebrow="Controls">
          <div className="space-y-3">
            {artifact.auth_steps.map((step) => (
              <div key={step} className="rounded-2xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">{step}</div>
            ))}
            {artifact.escalation_conditions.map((condition) => (
              <div key={condition} className="rounded-2xl border border-amber-100 bg-amber-50/80 p-3 text-sm text-amber-900">{condition}</div>
            ))}
          </div>
        </ListPanel>
      </div>

      <ListPanel title="Journeys & Tests" eyebrow="Artifacts">
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="space-y-3">
            {artifact.journeys.map((journey) => (
              <div key={journey.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{journey.name}</p>
                <ol className="mt-3 space-y-1 text-sm text-gray-600">
                  {journey.steps.map((step, index) => (
                    <li key={`${journey.name}-${index}`}>{index + 1}. {step}</li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          <div className="space-y-3">
            {artifact.suggested_tests.map((test) => (
              <div key={test.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <p className="text-sm font-semibold text-gray-900">{test.name}</p>
                <p className="mt-1 text-sm text-gray-600">Prompt: {test.user_message}</p>
                <p className="mt-1 text-sm text-gray-600">Expected: {test.expected_behavior}</p>
              </div>
            ))}
          </div>
        </div>
      </ListPanel>
    </div>
  );
}

export function IntelligenceStudio() {
  const [selectedReportId, setSelectedReportId] = useState<string | undefined>(undefined);
  const [question, setQuestion] = useState(starterQuestions[0]);
  const [answer, setAnswer] = useState<IntelligenceAnswer | null>(null);
  const [builderPrompt, setBuilderPrompt] = useState(
    'Build a customer service agent for order tracking, cancellation, and shipping-address changes. Escalate when the customer lacks the order number.'
  );
  const [selectedConnectors, setSelectedConnectors] = useState<string[]>(['Shopify', 'Amazon Connect']);

  const reportsQuery = useTranscriptReports();
  const reportQuery = useTranscriptReport(selectedReportId);
  const importMutation = useImportTranscriptArchive();
  const askMutation = useAskTranscriptReport();
  const applyMutation = useApplyTranscriptInsight();
  const buildMutation = useBuildAgentArtifact();

  useEffect(() => {
    if (!selectedReportId && reportsQuery.data && reportsQuery.data.length > 0) {
      setSelectedReportId(reportsQuery.data[0].report_id);
    }
  }, [reportsQuery.data, selectedReportId]);

  async function onArchiveSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const archiveBase64 = await fileToBase64(file);
      importMutation.mutate(
        { archive_name: file.name, archive_base64: archiveBase64 },
        {
          onSuccess: (report) => {
            toastSuccess('Transcript archive imported', `${report.conversation_count} conversations operationalized.`);
            setSelectedReportId(report.report_id);
          },
          onError: (error) => toastError('Archive import failed', error.message),
        }
      );
    } catch (error) {
      toastError('Archive import failed', error instanceof Error ? error.message : String(error));
    } finally {
      event.target.value = '';
    }
  }

  function onAsk() {
    if (!selectedReportId || !question.trim()) {
      toastError('Question required', 'Import an archive and enter a research question.');
      return;
    }
    askMutation.mutate(
      { reportId: selectedReportId, question },
      {
        onSuccess: (result) => setAnswer(result),
        onError: (error) => toastError('Question failed', error.message),
      }
    );
  }

  function onApplyInsight(insightId: string) {
    if (!selectedReportId) return;
    applyMutation.mutate(
      { reportId: selectedReportId, insight_id: insightId },
      {
        onSuccess: (result) => {
          toastSuccess('Change card drafted', `Insight converted into review card ${result.change_card.card_id}.`);
        },
        onError: (error) => toastError('Apply insight failed', error.message),
      }
    );
  }

  function toggleConnector(connector: string) {
    setSelectedConnectors((current) =>
      current.includes(connector) ? current.filter((item) => item !== connector) : [...current, connector]
    );
  }

  function onBuildArtifact() {
    if (!builderPrompt.trim()) {
      toastError('Prompt required', 'Describe the agent you want to build.');
      return;
    }
    buildMutation.mutate(
      { prompt: builderPrompt, connectors: selectedConnectors },
      {
        onError: (error) => toastError('Build failed', error.message),
      }
    );
  }

  const activeReport = reportQuery.data ?? importMutation.data ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Intelligence Studio"
        description="Operationalize transcript archives, ask natural-language questions about conversation failure, and turn insights into reviewable agent changes."
      />

      <section className="relative overflow-hidden rounded-[32px] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_35%),linear-gradient(135deg,#f8fbff_0%,#ffffff_52%,#f8fafc_100%)] p-6 shadow-sm shadow-slate-200/70">
        <div className="absolute inset-y-0 right-0 hidden w-1/3 bg-[radial-gradient(circle_at_center,_rgba(15,23,42,0.06),_transparent_60%)] xl:block" />
        <div className="relative grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-5">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-slate-900 p-3 text-white">
                <Brain className="h-5 w-5" />
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Natural-Language First</p>
                <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Ask, ingest, and operationalize in one place</h2>
              </div>
            </div>

            <p className="max-w-2xl text-sm leading-6 text-slate-600">
              Use transcript history as raw material for agent improvement. The studio turns messy archives into intents, procedures,
              FAQ seeds, workflow gaps, regression tests, and drafted change cards without disturbing the current optimization loop.
            </p>

            <div className="flex flex-wrap gap-3">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800">
                <UploadCloud className="h-4 w-4" />
                Import Transcript ZIP
                <input type="file" accept=".zip" className="hidden" onChange={onArchiveSelected} />
              </label>
              <button
                onClick={onAsk}
                disabled={!selectedReportId || askMutation.isPending}
                className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-60"
              >
                {askMutation.isPending ? 'Researching...' : 'Ask The Corpus'}
              </button>
              <button
                onClick={onBuildArtifact}
                disabled={buildMutation.isPending}
                className="rounded-full border border-sky-200 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-800 transition hover:bg-sky-100 disabled:opacity-60"
              >
                {buildMutation.isPending ? 'Drafting...' : 'Start From Prompt'}
              </button>
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white/90 p-5 backdrop-blur">
            <div className="flex items-center gap-2">
              <FileArchive className="h-4 w-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-slate-900">Archive Research</h3>
            </div>

            <div className="mt-4 space-y-3">
              {reportsQuery.isLoading && <LoadingSkeleton rows={3} />}
              {!reportsQuery.isLoading && (reportsQuery.data?.length ?? 0) === 0 && !importMutation.data && (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                  No archives imported yet. Upload a support-history ZIP to start mining intents and workflow gaps.
                </div>
              )}
              {(reportsQuery.data ?? []).map((report) => (
                <button
                  key={report.report_id}
                  onClick={() => setSelectedReportId(report.report_id)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                    selectedReportId === report.report_id
                      ? 'border-sky-200 bg-sky-50'
                      : 'border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">{report.archive_name}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {report.conversation_count} conversations · {report.languages.join(', ')} · {formatTimestamp(report.created_at)}
                      </p>
                    </div>
                    <span className="rounded-full bg-white px-2 py-1 text-xs font-medium text-slate-600">{report.report_id}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/60">
          <div className="flex items-center gap-2">
            <MessageSquareText className="h-4 w-4 text-gray-500" />
            <h3 className="text-lg font-semibold tracking-tight text-gray-900">Ask The Conversation Warehouse</h3>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Ask plain-language questions about the imported corpus instead of digging through dashboards.
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {starterQuestions.map((item) => (
              <button
                key={item}
                onClick={() => setQuestion(item)}
                className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-600 transition hover:bg-gray-100"
              >
                {item}
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              className="min-h-[96px] flex-1 rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-800 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              placeholder="Why are people transferring to live support?"
            />
            <button
              onClick={onAsk}
              disabled={!selectedReportId || askMutation.isPending}
              className="rounded-2xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              {askMutation.isPending ? 'Researching...' : 'Run Analysis'}
            </button>
          </div>

          <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4">
            {!answer && (
              <p className="text-sm text-gray-500">
                Import an archive and ask a question to get quantified root-cause reporting plus prescriptive recommendations.
              </p>
            )}
            {answer && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700">
                    Share {formatPercent(answer.metrics.share)}
                  </span>
                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-600">
                    {answer.metrics.count}/{answer.metrics.total} conversations
                  </span>
                  {answer.recommended_insight_id && (
                    <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-600">
                      Insight {answer.recommended_insight_id}
                    </span>
                  )}
                </div>
                <p className="text-sm leading-6 text-gray-700">{answer.answer}</p>
                {answer.evidence.length > 0 && (
                  <div className="rounded-2xl bg-white p-3">
                    <p className="text-xs uppercase tracking-[0.16em] text-gray-400">Evidence</p>
                    <ul className="mt-2 space-y-1.5 text-sm text-gray-600">
                      {answer.evidence.map((item) => (
                        <li key={item}>“{item}”</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm shadow-gray-100/60">
          <div className="flex items-center gap-2">
            <WandSparkles className="h-4 w-4 text-gray-500" />
            <h3 className="text-lg font-semibold tracking-tight text-gray-900">Prompt-To-Agent Builder</h3>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Start from a blank slate prompt and generate structured agent artifacts instead of manually wiring every flow.
          </p>

          <textarea
            value={builderPrompt}
            onChange={(event) => setBuilderPrompt(event.target.value)}
            rows={6}
            className="mt-4 w-full rounded-2xl border border-gray-300 px-4 py-3 text-sm text-gray-800 outline-none transition focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
            placeholder="Describe the agent you want to create..."
          />

          <div className="mt-4 flex flex-wrap gap-2">
            {connectorOptions.map((connector) => {
              const active = selectedConnectors.includes(connector);
              return (
                <button
                  key={connector}
                  onClick={() => toggleConnector(connector)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                    active
                      ? 'border-sky-200 bg-sky-50 text-sky-800'
                      : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {connector}
                </button>
              );
            })}
          </div>

          <button
            onClick={onBuildArtifact}
            disabled={buildMutation.isPending}
            className="mt-4 inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            <Sparkles className="h-4 w-4" />
            {buildMutation.isPending ? 'Drafting agent...' : 'Generate Agent Artifact'}
          </button>
        </section>
      </div>

      {reportQuery.isLoading && <LoadingSkeleton rows={8} />}
      {activeReport && <ReportHighlights report={activeReport} onApplyInsight={onApplyInsight} applyPending={applyMutation.isPending} />}
      {buildMutation.data && <BuilderResult artifact={buildMutation.data} />}
    </div>
  );
}
