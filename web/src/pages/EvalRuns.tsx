import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { FlaskConical, Plus, X, Wand2 } from 'lucide-react';
import { useApplyCurriculum, useConfigs, useCurriculumBatches, useEvalRuns, useGenerateCurriculum, useStartEval } from '../lib/api';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { ScoreDisplay } from '../components/ScoreDisplay';
import { EvalGenerator } from '../components/EvalGenerator';
import { GeneratedEvalReview } from '../components/GeneratedEvalReview';
import { wsClient } from '../lib/websocket';
import { toastError, toastInfo, toastSuccess } from '../lib/toast';
import { formatTimestamp, statusVariant } from '../lib/utils';

export function EvalRuns() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: runs, isLoading, isError, refetch } = useEvalRuns();
  const { data: configs } = useConfigs();
  const { data: curriculumData } = useCurriculumBatches();
  const startEval = useStartEval();
  const generateCurriculum = useGenerateCurriculum();
  const applyCurriculum = useApplyCurriculum();

  const [showForm, setShowForm] = useState(false);
  const [showGenerator, setShowGenerator] = useState(false);
  const [generatedSuiteId, setGeneratedSuiteId] = useState<string | null>(null);
  const [configVersion, setConfigVersion] = useState<string>('');
  const [category, setCategory] = useState('');
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const showCreateForm = showForm || searchParams.get('new') === '1';

  useEffect(() => {
    const unsubscribe = wsClient.onMessage('eval_complete', (payload) => {
      const data = payload as { task_id: string; composite: number; passed: number; total: number };
      toastSuccess(
        `Eval ${data.task_id.slice(0, 8)} completed`,
        `Composite ${(data.composite * 100).toFixed(1)} · ${data.passed}/${data.total} passed`
      );
      refetch();
    });

    return () => unsubscribe();
  }, [refetch]);

  const comparisonRuns = useMemo(() => {
    if (!runs || selectedRuns.length !== 2) return [];
    return runs.filter((run) => selectedRuns.includes(run.run_id));
  }, [runs, selectedRuns]);

  function handleStartEval() {
    const selectedConfig = configs?.find((entry) => String(entry.version) === configVersion);
    const configPath = selectedConfig ? `configs/${selectedConfig.filename}` : undefined;

    startEval.mutate(
      {
        config_path: configPath,
        category: category.trim() || undefined,
      },
      {
        onSuccess: (response) => {
          toastInfo(`Eval ${response.task_id.slice(0, 8)} started`, 'You can monitor live status from this table.');
          setShowForm(false);
          setConfigVersion('');
          setCategory('');
          const next = new URLSearchParams(searchParams);
          next.delete('new');
          setSearchParams(next);
        },
        onError: (error) => {
          toastError('Failed to start eval', error.message);
        },
      }
    );
  }

  function toggleSelectedRun(runId: string) {
    setSelectedRuns((current) => {
      if (current.includes(runId)) {
        return current.filter((entry) => entry !== runId);
      }
      if (current.length >= 2) {
        toastInfo('Comparison limit reached', 'Select at most two runs at a time.');
        return current;
      }
      return [...current, runId];
    });
  }

  function closeForm() {
    setShowForm(false);
    const next = new URLSearchParams(searchParams);
    next.delete('new');
    setSearchParams(next);
  }

  function handleGenerateCurriculum() {
    generateCurriculum.mutate(
      {},
      {
        onSuccess: (payload) => {
          toastSuccess(
            'Curriculum generated',
            `Created batch ${payload.batch.batch_id.slice(0, 8)} with ${payload.batch.prompt_count} prompts.`
          );
        },
        onError: (err) => toastError('Curriculum generation failed', err.message),
      }
    );
  }

  function handleApplyCurriculum(batchId: string) {
    applyCurriculum.mutate(
      { batch_id: batchId },
      {
        onSuccess: (payload) => {
          toastSuccess('Curriculum applied', `${payload.applied_count} prompts added to active eval set.`);
        },
        onError: (err) => toastError('Apply failed', err.message),
      }
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={4} />
        <LoadingSkeleton rows={7} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Eval Runs"
        description="Launch evaluations, inspect progress, and compare the quality impact of different runs."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setShowGenerator(true); setGeneratedSuiteId(null); }}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              <Wand2 className="h-4 w-4" />
              Generate Evals
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              <Plus className="h-4 w-4" />
              New Eval Run
            </button>
          </div>
        }
      />

      {showGenerator && !generatedSuiteId && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">AI Eval Generation</h3>
            <button
              onClick={() => setShowGenerator(false)}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <EvalGenerator
            onSuiteGenerated={(suiteId) => setGeneratedSuiteId(suiteId)}
          />
        </section>
      )}

      {generatedSuiteId && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Review Generated Evals</h3>
            <button
              onClick={() => { setGeneratedSuiteId(null); setShowGenerator(false); }}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <GeneratedEvalReview
            suiteId={generatedSuiteId}
            onAccepted={() => {
              toastSuccess('Eval suite accepted', 'Generated cases are now available for eval runs.');
              setGeneratedSuiteId(null);
              setShowGenerator(false);
            }}
          />
        </section>
      )}

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load eval runs. Try refreshing the page.
        </div>
      )}

      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Curriculum</h3>
            <p className="mt-1 text-xs text-gray-600">
              Self-play prompts synthesized from recent failures to continuously harden evaluations.
            </p>
          </div>
          <button
            onClick={handleGenerateCurriculum}
            disabled={generateCurriculum.isPending}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {generateCurriculum.isPending ? 'Generating…' : 'Generate Harder Tests'}
          </button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1.4fr,1fr]">
          <div className="space-y-2">
            {(curriculumData?.batches || []).length === 0 && (
              <p className="rounded-md border border-dashed border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
                No curriculum batches yet. Generate one from recent failure clusters.
              </p>
            )}
            {(curriculumData?.batches || []).slice(0, 5).map((batch) => (
              <div key={batch.batch_id} className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-xs text-gray-700">{batch.batch_id}</p>
                  <button
                    onClick={() => handleApplyCurriculum(batch.batch_id)}
                    disabled={applyCurriculum.isPending}
                    className="rounded-md border border-gray-300 bg-white px-2 py-0.5 text-[11px] font-medium text-gray-700 hover:bg-gray-100"
                  >
                    Apply
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-gray-600">
                  prompts={batch.prompt_count} · active={batch.applied_count}
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(batch.difficulty_distribution).map(([tier, count]) => (
                    <span key={tier} className="rounded bg-white px-1.5 py-0.5 text-[10px] text-gray-600">
                      {tier}: {count}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
            <p className="text-xs font-semibold text-gray-700">Difficulty progression</p>
            <div className="mt-2 space-y-2">
              {(curriculumData?.progression || []).slice(0, 6).map((point) => (
                <div key={point.batch_id} className="space-y-1">
                  <div className="flex items-center justify-between text-[11px] text-gray-500">
                    <span className="font-mono">{point.batch_id.slice(0, 8)}</span>
                    <span>{(point.average_difficulty * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-gray-200">
                    <div
                      className="h-full rounded-full bg-gray-700"
                      style={{ width: `${Math.min(point.average_difficulty * 100, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
              {(curriculumData?.progression || []).length === 0 && (
                <p className="text-[11px] text-gray-500">Difficulty progression appears after the first generated batch.</p>
              )}
            </div>
          </div>
        </div>
      </section>

      {showCreateForm && (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Start New Evaluation</h3>
            <button onClick={closeForm} className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Config Version</label>
              <select
                value={configVersion}
                onChange={(event) => setConfigVersion(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">Latest active</option>
                {(configs || []).map((config) => (
                  <option key={config.version} value={config.version}>
                    v{config.version} · {config.status}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs text-gray-500">Category</label>
              <input
                type="text"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder="Optional, e.g. safety"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div className="flex items-end">
              <button
                onClick={handleStartEval}
                disabled={startEval.isPending}
                className="w-full rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
              >
                {startEval.isPending ? 'Starting...' : 'Start Eval'}
              </button>
            </div>
          </div>
        </section>
      )}

      {comparisonRuns.length === 2 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Comparison Mode</h3>
            <button
              onClick={() => setSelectedRuns([])}
              className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50"
            >
              Clear
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {comparisonRuns.map((run) => (
              <div key={run.run_id} className="rounded-lg border border-gray-200 p-4">
                <div className="flex items-center justify-between">
                  <p className="font-mono text-xs text-gray-600">{run.run_id.slice(0, 12)}</p>
                  <StatusBadge variant={statusVariant(run.status)} label={run.status} />
                </div>
                <div className="mt-2">
                  <ScoreDisplay score={run.composite_score} size="lg" />
                  <p className="mt-1 text-xs text-gray-500">
                    {run.passed_cases}/{run.total_cases} passed · {formatTimestamp(run.timestamp)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {runs && runs.length > 0 ? (
        <section className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Compare</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Run ID</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Started</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Score</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Cases</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">Action</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run, index) => (
                  <tr key={run.run_id} className={index % 2 ? 'bg-gray-50/60' : ''}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selectedRuns.includes(run.run_id)}
                        onChange={() => toggleSelectedRun(run.run_id)}
                        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-gray-700">{run.run_id.slice(0, 8)}</td>
                    <td className="px-3 py-2 text-gray-600">{formatTimestamp(run.timestamp)}</td>
                    <td className="px-3 py-2">
                      <div className="space-y-1">
                        <StatusBadge variant={statusVariant(run.status)} label={run.status} />
                        {run.status === 'running' && (
                          <p className="text-xs text-gray-500">Progress: {run.progress}%</p>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 font-medium text-gray-900">{run.composite_score.toFixed(1)}</td>
                    <td className="px-3 py-2 text-gray-600">
                      {run.total_cases > 0 ? `${run.passed_cases}/${run.total_cases}` : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => navigate(`/evals/${run.run_id}`)}
                        className="rounded border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <EmptyState
          icon={FlaskConical}
          title="No eval runs yet"
          description="Run your first eval:"
          cliHint="autoagent eval run"
          actionLabel="Create Eval Run"
          onAction={() => setShowForm(true)}
        />
      )}
    </div>
  );
}
