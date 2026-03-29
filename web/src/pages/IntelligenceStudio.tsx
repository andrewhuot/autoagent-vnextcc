import { useEffect, useState, type ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, FileArchive, MessageSquareText, Sparkles, UploadCloud, WandSparkles } from 'lucide-react';
import {
  useApplyTranscriptInsight,
  useAskTranscriptReport,
  useBuildAgentArtifact,
  useDeepResearchReport,
  useImportTranscriptArchive,
  useKnowledgeAsset,
  useRunAutonomousLoop,
  useTranscriptReport,
  useTranscriptReports,
} from '../lib/api';
import { BuilderResult, ListPanel, ReportHighlights, SummaryCard } from '../components/IntelligenceComponents';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { PageHeader } from '../components/PageHeader';
import { toastError, toastSuccess } from '../lib/toast';
import type {
  ApplyInsightResult,
  AutonomousLoopResult,
  DeepResearchReport,
  IntelligenceAnswer,
} from '../lib/types';
import { formatTimestamp, formatPercent } from '../lib/utils';

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

export function IntelligenceStudio() {
  const navigate = useNavigate();
  const [selectedReportId, setSelectedReportId] = useState<string | undefined>(undefined);
  const [question, setQuestion] = useState(starterQuestions[0]);
  const [answer, setAnswer] = useState<IntelligenceAnswer | null>(null);
  const [deepResearch, setDeepResearch] = useState<DeepResearchReport | null>(null);
  const [autonomousResult, setAutonomousResult] = useState<AutonomousLoopResult | null>(null);
  const [lastApplyResult, setLastApplyResult] = useState<ApplyInsightResult | null>(null);
  const [builderPrompt, setBuilderPrompt] = useState(
    'Build a customer service agent for order tracking, cancellation, and shipping-address changes. Escalate when the customer lacks the order number.'
  );
  const [selectedConnectors, setSelectedConnectors] = useState<string[]>(['Shopify', 'Amazon Connect']);

  const reportsQuery = useTranscriptReports();
  const reportQuery = useTranscriptReport(selectedReportId);
  const importMutation = useImportTranscriptArchive();
  const askMutation = useAskTranscriptReport();
  const applyMutation = useApplyTranscriptInsight();
  const deepResearchMutation = useDeepResearchReport();
  const autonomousMutation = useRunAutonomousLoop();
  const buildMutation = useBuildAgentArtifact();
  const knowledgeAssetId = (reportQuery.data ?? importMutation.data)?.knowledge_asset?.asset_id;
  const knowledgeAssetQuery = useKnowledgeAsset(knowledgeAssetId);

  useEffect(() => {
    if (!selectedReportId && reportsQuery.data && reportsQuery.data.length > 0) {
      setSelectedReportId(reportsQuery.data[0].report_id);
    }
  }, [reportsQuery.data, selectedReportId]);

  useEffect(() => {
    setAnswer(null);
    setDeepResearch(null);
    setAutonomousResult(null);
    setLastApplyResult(null);
  }, [selectedReportId]);

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
        onSuccess: (result) => {
          setAnswer(result);
          setDeepResearch(result.deep_research ?? null);
        },
        onError: (error) => toastError('Question failed', error.message),
      }
    );
  }

  function onDeepResearch() {
    if (!selectedReportId || !question.trim()) {
      toastError('Question required', 'Import an archive and enter a research question.');
      return;
    }
    deepResearchMutation.mutate(
      { reportId: selectedReportId, question },
      {
        onSuccess: (result) => {
          setDeepResearch(result);
          toastSuccess('Deep research complete', `${result.root_causes.length} quantified root causes identified.`);
        },
        onError: (error) => toastError('Deep research failed', error.message),
      }
    );
  }

  function onRunAutonomousLoop() {
    if (!selectedReportId) {
      toastError('Report required', 'Import an archive before running the autonomous loop.');
      return;
    }
    autonomousMutation.mutate(
      { reportId: selectedReportId, auto_ship: false },
      {
        onSuccess: (result) => {
          setAutonomousResult(result);
          toastSuccess(
            'Autonomous loop complete',
            `Change card ${result.change_card_id} created with ${formatPercent(result.pipeline.test.pass_rate)} sandbox pass rate.`
          );
        },
        onError: (error) => toastError('Autonomous loop failed', error.message),
      }
    );
  }

  function onApplyInsight(insightId: string) {
    if (!selectedReportId) return;
    applyMutation.mutate(
      { reportId: selectedReportId, insight_id: insightId },
      {
        onSuccess: (result) => {
          setLastApplyResult(result);
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
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        Canonical build path: create your agent artifact here, then run evaluation, optimization, review, and CX deployment.
      </div>

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
              <button
                onClick={onDeepResearch}
                disabled={!selectedReportId || deepResearchMutation.isPending}
                className="rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-100 disabled:opacity-60"
              >
                {deepResearchMutation.isPending ? 'Analyzing...' : 'Deep Research'}
              </button>
              <button
                onClick={onRunAutonomousLoop}
                disabled={!selectedReportId || autonomousMutation.isPending}
                className="rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-semibold text-amber-800 transition hover:bg-amber-100 disabled:opacity-60"
              >
                {autonomousMutation.isPending ? 'Running Loop...' : 'Run Autonomous Loop'}
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
              <button
                onClick={onDeepResearch}
                disabled={!selectedReportId || deepResearchMutation.isPending}
                className="rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-3 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-100 disabled:opacity-60"
              >
                {deepResearchMutation.isPending ? 'Analyzing...' : 'Run Deep Research'}
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
      {lastApplyResult && (
        <ListPanel title="Auto-Generated Simulation Bundle" eyebrow="Change Validation">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="space-y-3">
              {lastApplyResult.auto_simulation.generated_tests.map((test) => (
                <div key={test.name} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">{test.name}</p>
                    <span className="rounded-full bg-white px-2 py-1 text-xs font-medium text-gray-600">{test.difficulty}</span>
                  </div>
                  <p className="mt-2 text-sm text-gray-600">Prompt: {test.user_message}</p>
                  <p className="mt-1 text-sm text-gray-600">Expected: {test.expected_behavior}</p>
                </div>
              ))}
            </div>
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <p className="text-sm font-semibold text-gray-900">Sandbox Validation</p>
              <div className="mt-3 space-y-2 text-sm text-gray-600">
                <p>Pass Rate: {formatPercent(lastApplyResult.auto_simulation.sandbox_validation.pass_rate)}</p>
                <p>Total: {lastApplyResult.auto_simulation.sandbox_validation.total_conversations}</p>
                <p>Passed: {lastApplyResult.auto_simulation.sandbox_validation.passed}</p>
                <p>Failed: {lastApplyResult.auto_simulation.sandbox_validation.failed}</p>
                <p>Avg Latency: {lastApplyResult.auto_simulation.sandbox_validation.avg_latency_ms.toFixed(1)}ms</p>
              </div>
            </div>
          </div>
        </ListPanel>
      )}

      {knowledgeAssetQuery.data && (
        <ListPanel title="Durable Knowledge Asset" eyebrow="Knowledge Base">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
              <p className="text-xs uppercase tracking-[0.16em] text-gray-400">Asset</p>
              <p className="mt-2 text-sm font-semibold text-gray-900">{knowledgeAssetQuery.data.asset_id}</p>
              <p className="mt-1 text-sm text-gray-600">{knowledgeAssetQuery.data.archive_name}</p>
              <p className="mt-1 text-sm text-gray-600">{knowledgeAssetQuery.data.entry_count} entries</p>
            </div>
            <div className="space-y-3">
              {knowledgeAssetQuery.data.entries.slice(0, 5).map((entry, index) => (
                <div key={`${entry.type}-${index}`} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-gray-400">{entry.type}</p>
                  <p className="mt-2 text-sm text-gray-700">
                    {entry.question || entry.title || entry.example || entry.intent || 'Knowledge entry'}
                  </p>
                  {(entry.answer || entry.description || entry.response) && (
                    <p className="mt-1 text-sm text-gray-600">{entry.answer || entry.description || entry.response}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </ListPanel>
      )}

      {deepResearch && (
        <ListPanel title="Deep Research Findings" eyebrow="Explorer">
          <div className="grid gap-4 xl:grid-cols-2">
            <div className="space-y-3">
              {deepResearch.root_causes.slice(0, 5).map((cause) => (
                <div key={cause.reason} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">{cause.reason}</p>
                    <span className="rounded-full bg-white px-2 py-1 text-xs font-medium text-gray-600">
                      {cause.attribution_pct.toFixed(1)}%
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{cause.count} conversations</p>
                  {cause.evidence.length > 0 && <p className="mt-2 text-sm text-gray-600">“{cause.evidence[0]}”</p>}
                </div>
              ))}
            </div>
            <div className="space-y-3">
              {deepResearch.recommendations.map((recommendation) => (
                <div key={recommendation} className="rounded-2xl border border-sky-100 bg-sky-50/70 p-3 text-sm text-slate-700">
                  {recommendation}
                </div>
              ))}
            </div>
          </div>
        </ListPanel>
      )}

      {autonomousResult && (
        <ListPanel title="Autonomous Improvement Pipeline" eyebrow="Analyze -> Improve -> Test -> Ship">
          <div className="grid gap-4 xl:grid-cols-4">
            <SummaryCard label="Analyze" value={autonomousResult.pipeline.analyze.status} />
            <SummaryCard label="Improve" value={autonomousResult.pipeline.improve.status} />
            <SummaryCard label="Test" value={formatPercent(autonomousResult.pipeline.test.pass_rate)} />
            <SummaryCard label="Ship" value={autonomousResult.pipeline.ship.status} />
          </div>
          <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
            <p>Change Card: {autonomousResult.change_card_id}</p>
            <p className="mt-1">Drafted Prompt: {autonomousResult.drafted_change_prompt}</p>
          </div>
        </ListPanel>
      )}

      {buildMutation.data && (
        <>
          <ListPanel title="Golden Path Next Steps" eyebrow="Build -> Eval -> Optimize -> Deploy">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <button
                onClick={() => navigate('/evals?new=1')}
                className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-800 transition hover:border-gray-300 hover:bg-gray-50"
              >
                1. Run Evaluation
              </button>
              <button
                onClick={() => navigate('/optimize?new=1')}
                className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-800 transition hover:border-gray-300 hover:bg-gray-50"
              >
                2. Start Optimization
              </button>
              <button
                onClick={() => navigate('/changes')}
                className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-800 transition hover:border-gray-300 hover:bg-gray-50"
              >
                3. Review Changes
              </button>
              <button
                onClick={() => navigate('/cx/deploy')}
                className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-800 transition hover:bg-sky-100"
              >
                4. Deploy to CX
              </button>
            </div>
          </ListPanel>
          <BuilderResult artifact={buildMutation.data} />
        </>
      )}
    </div>
  );
}
