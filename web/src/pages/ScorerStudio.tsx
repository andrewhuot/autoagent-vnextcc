import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, RefreshCw, FlaskConical, Plus, Sparkles } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { classNames } from '../lib/utils';

const API_BASE = '/api';

interface ScorerDimension {
  name: string;
  description: string;
  grader_type: string;
  weight: number;
  layer: string;
}

interface ScorerDetail {
  name: string;
  description: string;
  dimensions: ScorerDimension[];
  created_at: string;
}

interface ScorerListItem {
  name: string;
  description: string;
  dimension_count: number;
  created_at: string;
}

interface CompileResult {
  name: string;
  description: string;
  dimensions: ScorerDimension[];
}

interface TestResult {
  passed: boolean;
  scores: Record<string, number>;
  details: string;
}

interface RawScorerDimension {
  name?: string;
  description?: string;
  grader_type?: string;
  weight?: number;
  layer?: string;
}

interface RawScorerSpec {
  name?: string;
  description?: string;
  source_nl?: string;
  compiled_at?: string;
  created_at?: string;
  dimensions?: RawScorerDimension[];
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const layerColors: Record<string, string> = {
  safety: 'bg-red-50 text-red-700 border-red-200',
  quality: 'bg-blue-50 text-blue-700 border-blue-200',
  style: 'bg-purple-50 text-purple-700 border-purple-200',
  task: 'bg-green-50 text-green-700 border-green-200',
  default: 'bg-gray-50 text-gray-700 border-gray-200',
};

function layerBadgeClass(layer: string): string {
  return layerColors[layer] ?? layerColors['default'];
}

function normalizeDimensions(dimensions: RawScorerDimension[] | undefined): ScorerDimension[] {
  return (dimensions ?? []).map((dimension) => ({
    name: dimension.name ?? 'unnamed',
    description: dimension.description ?? '',
    grader_type: dimension.grader_type ?? 'llm_judge',
    weight: dimension.weight ?? 0,
    layer: dimension.layer ?? 'default',
  }));
}

function normalizeScorerSpec(raw: RawScorerSpec | undefined): ScorerDetail {
  return {
    name: raw?.name ?? 'unnamed',
    description: raw?.description ?? raw?.source_nl ?? '',
    dimensions: normalizeDimensions(raw?.dimensions),
    created_at: raw?.created_at ?? raw?.compiled_at ?? new Date().toISOString(),
  };
}

function normalizeCompileResult(payload: unknown): CompileResult {
  const wrapper = (typeof payload === 'object' && payload !== null) ? payload as { scorer?: RawScorerSpec } : {};
  const scorer = wrapper.scorer;
  const normalized = normalizeScorerSpec(scorer);

  return {
    name: normalized.name,
    description: normalized.description,
    dimensions: normalized.dimensions,
  };
}

function normalizeScorerList(payload: unknown): ScorerListItem[] {
  const wrapper = (typeof payload === 'object' && payload !== null) ? payload as { scorers?: RawScorerSpec[] } : {};
  const scorers = Array.isArray(wrapper.scorers) ? wrapper.scorers : [];

  return scorers.map((scorer) => ({
    name: scorer.name ?? 'unnamed',
    description: scorer.description ?? scorer.source_nl ?? '',
    dimension_count: Array.isArray(scorer.dimensions) ? scorer.dimensions.length : 0,
    created_at: scorer.created_at ?? scorer.compiled_at ?? new Date().toISOString(),
  }));
}

function normalizeScorerDetail(payload: unknown): ScorerDetail {
  const wrapper = (typeof payload === 'object' && payload !== null) ? payload as { scorer?: RawScorerSpec } : {};
  return normalizeScorerSpec(wrapper.scorer);
}

function normalizeTestResult(payload: unknown): TestResult {
  const wrapper = (typeof payload === 'object' && payload !== null) ? payload as {
    passed?: boolean;
    scores?: {
      aggregate?: number;
      per_dimension?: Record<string, number | { score?: number; passed?: boolean }>;
    };
  } : {};
  const perDimension = wrapper.scores?.per_dimension ?? {};
  const scores = Object.fromEntries(
    Object.entries(perDimension).map(([key, value]) => [
      key,
      typeof value === 'number' ? value : value?.score ?? 0,
    ])
  );
  const aggregate = wrapper.scores?.aggregate ?? 0;
  const passed = wrapper.passed ?? Object.values(perDimension).every((value) => {
    if (typeof value === 'number') {
      return value >= 0.5;
    }
    return value?.passed ?? true;
  });

  return {
    passed,
    scores: Object.keys(scores).length > 0 ? scores : { aggregate },
    details: `Aggregate score ${aggregate.toFixed(2)}`,
  };
}

export function ScorerStudio() {
  const queryClient = useQueryClient();

  const [nlInput, setNlInput] = useState('');
  const [refineInput, setRefineInput] = useState('');
  const [compiledScorer, setCompiledScorer] = useState<CompileResult | null>(null);
  const [selectedScorer, setSelectedScorer] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // List saved scorers
  const scorerListQuery = useQuery({
    queryKey: ['scorers'],
    queryFn: async () => {
      const payload = await fetchJson<unknown>('/scorers');
      return normalizeScorerList(payload);
    },
  });

  // Get selected scorer details
  const scorerDetailQuery = useQuery({
    queryKey: ['scorer', selectedScorer],
    queryFn: async () => {
      const payload = await fetchJson<unknown>(`/scorers/${selectedScorer}`);
      return normalizeScorerDetail(payload);
    },
    enabled: !!selectedScorer,
  });

  // Compile mutation
  const compileMutation = useMutation({
    mutationFn: (input: string) =>
      fetchJson<unknown>('/scorers/create', {
        method: 'POST',
        body: JSON.stringify({ description: input }),
      }),
    onSuccess: (payload) => {
      setCompiledScorer(normalizeCompileResult(payload));
      setTestResult(null);
      queryClient.invalidateQueries({ queryKey: ['scorers'] });
    },
  });

  // Save mutation (re-compile to persist)
  const saveMutation = useMutation({
    mutationFn: (scorer: CompileResult) =>
      fetchJson<unknown>('/scorers/create', {
        method: 'POST',
        body: JSON.stringify({
          description: scorer.description || nlInput,
          name: scorer.name,
        }),
      }),
    onSuccess: (payload) => {
      const saved = normalizeCompileResult(payload);
      setCompiledScorer(saved);
      setSelectedScorer(saved.name);
      queryClient.invalidateQueries({ queryKey: ['scorers'] });
    },
  });

  // Refine mutation
  const refineMutation = useMutation({
    mutationFn: ({ name, criteria }: { name: string; criteria: string }) =>
      fetchJson<unknown>(`/scorers/${name}/refine`, {
        method: 'POST',
        body: JSON.stringify({ description: criteria }),
      }),
    onSuccess: (payload) => {
      setCompiledScorer(normalizeCompileResult(payload));
      setTestResult(null);
      queryClient.invalidateQueries({ queryKey: ['scorers'] });
    },
  });

  // Test mutation
  const testMutation = useMutation({
    mutationFn: (name: string) =>
      fetchJson<unknown>(`/scorers/${name}/test`, {
        method: 'POST',
        body: JSON.stringify({
          eval_result: {
            case_id: 'studio-smoke-test',
            category: 'happy_path',
            passed: true,
            quality_score: 0.82,
            safety_passed: true,
            latency_ms: 420,
            token_count: 160,
            tool_use_accuracy: 0.9,
            satisfaction_proxy: 0.88,
          },
        }),
      }),
    onSuccess: (payload) => {
      setTestResult(normalizeTestResult(payload));
    },
  });

  function handleCompile() {
    if (!nlInput.trim()) return;
    compileMutation.mutate(nlInput);
  }

  function handleSave() {
    if (!compiledScorer) return;
    saveMutation.mutate(compiledScorer);
  }

  function handleRefine() {
    if (!refineInput.trim() || !compiledScorer) return;
    refineMutation.mutate({ name: compiledScorer.name, criteria: refineInput });
    setRefineInput('');
  }

  function handleTest() {
    if (!compiledScorer) return;
    testMutation.mutate(compiledScorer.name);
  }

  function handleSelectScorer(name: string) {
    setSelectedScorer(name);
    setCompiledScorer(null);
    setTestResult(null);
  }

  const activeDimensions = compiledScorer?.dimensions ?? scorerDetailQuery.data?.dimensions ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="NL Scorer Studio"
        description="Define evaluation scorers from natural language, compile to dimensions, refine, and test"
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        {/* Main editor area */}
        <div className="space-y-4">
          {/* NL Input */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <label className="text-xs font-medium text-gray-500">Describe your scoring criteria</label>
            <textarea
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
              rows={5}
              placeholder="e.g. The response should be helpful, accurate, and cite sources. Safety violations like harmful content should fail the evaluation immediately."
              className="mt-2 w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={handleCompile}
                disabled={compileMutation.isPending || !nlInput.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
              >
                <Sparkles className="h-4 w-4" />
                {compileMutation.isPending ? 'Compiling...' : 'Compile'}
              </button>
              {compileMutation.isError && (
                <span className="text-xs text-red-600">Failed to compile. Try again.</span>
              )}
            </div>
          </div>

          {/* Compiled dimensions */}
          {activeDimensions.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-900">
                  Dimensions ({activeDimensions.length})
                </h3>
                <div className="flex items-center gap-2">
                  {compiledScorer && (
                    <>
                      <button
                        onClick={handleTest}
                        disabled={testMutation.isPending}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
                      >
                        <FlaskConical className="h-3.5 w-3.5" />
                        {testMutation.isPending ? 'Testing...' : 'Test'}
                      </button>
                      <button
                        onClick={handleSave}
                        disabled={saveMutation.isPending}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700 disabled:opacity-60"
                      >
                        <Save className="h-3.5 w-3.5" />
                        {saveMutation.isPending ? 'Saving...' : 'Save'}
                      </button>
                    </>
                  )}
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {activeDimensions.map((dim) => (
                  <div
                    key={dim.name}
                    className="rounded-xl border border-gray-200 bg-white p-3"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{dim.name}</span>
                      <span
                        className={classNames(
                          'rounded-md border px-1.5 py-0.5 text-[10px] font-medium',
                          layerBadgeClass(dim.layer)
                        )}
                      >
                        {dim.layer}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">{dim.description}</p>
                    <div className="mt-2 flex items-center gap-3 text-[11px] text-gray-400">
                      <span>Grader: {dim.grader_type}</span>
                      <span>Weight: {dim.weight}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Refine input */}
          {compiledScorer && (
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <label className="text-xs font-medium text-gray-500">Refine criteria</label>
              <div className="mt-2 flex gap-2">
                <input
                  type="text"
                  value={refineInput}
                  onChange={(e) => setRefineInput(e.target.value)}
                  placeholder="Add more criteria or adjust existing ones..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none"
                />
                <button
                  onClick={handleRefine}
                  disabled={refineMutation.isPending || !refineInput.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
                >
                  <RefreshCw className={classNames('h-4 w-4', refineMutation.isPending ? 'animate-spin' : '')} />
                  Refine
                </button>
              </div>
            </div>
          )}

          {/* Test results */}
          {testResult && (
            <div
              className={classNames(
                'rounded-xl border p-4',
                testResult.passed
                  ? 'border-green-200 bg-green-50'
                  : 'border-red-200 bg-red-50'
              )}
            >
              <div className="flex items-center gap-2">
                <span
                  className={classNames(
                    'rounded-md px-2 py-0.5 text-xs font-medium',
                    testResult.passed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  )}
                >
                  {testResult.passed ? 'PASS' : 'FAIL'}
                </span>
                <h4 className="text-sm font-medium text-gray-900">Test Results</h4>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {Object.entries(testResult.scores).map(([key, value]) => (
                  <div key={key} className="rounded-lg border border-gray-200 bg-white px-3 py-2">
                    <p className="text-xs text-gray-500">{key}</p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums text-gray-900">
                      {(value * 100).toFixed(1)}%
                    </p>
                  </div>
                ))}
              </div>
              {testResult.details && (
                <p className="mt-2 text-xs text-gray-600">{testResult.details}</p>
              )}
            </div>
          )}
        </div>

        {/* Sidebar: saved scorers */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-gray-900">Saved Scorers</h3>

          {scorerListQuery.isLoading && (
            <div className="flex h-20 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-xs text-gray-500">
              Loading...
            </div>
          )}

          {scorerListQuery.isError && (
            <div className="flex h-20 items-center justify-center rounded-xl border border-dashed border-red-200 bg-red-50 text-xs text-red-600">
              Failed to load.
            </div>
          )}

          {!scorerListQuery.isLoading && !scorerListQuery.isError && (
            <>
              {(scorerListQuery.data ?? []).length === 0 ? (
                <div className="flex h-20 items-center justify-center rounded-xl border border-dashed border-gray-200 bg-gray-50 text-xs text-gray-500">
                  No scorers saved yet.
                </div>
              ) : (
                <div className="space-y-1">
                  {(scorerListQuery.data ?? []).map((scorer) => (
                    <button
                      key={scorer.name}
                      onClick={() => handleSelectScorer(scorer.name)}
                      className={classNames(
                        'w-full rounded-lg border px-3 py-2 text-left transition-colors',
                        selectedScorer === scorer.name
                          ? 'border-blue-300 bg-blue-50'
                          : 'border-gray-200 bg-white hover:bg-gray-50'
                      )}
                    >
                      <p className="text-sm font-medium text-gray-900">{scorer.name}</p>
                      <p className="mt-0.5 truncate text-xs text-gray-500">{scorer.description}</p>
                      <p className="mt-1 text-[11px] text-gray-400">
                        {scorer.dimension_count} dimensions
                      </p>
                    </button>
                  ))}
                </div>
              )}

              <button
                onClick={() => {
                  setSelectedScorer(null);
                  setCompiledScorer(null);
                  setNlInput('');
                  setTestResult(null);
                }}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-gray-300 px-3 py-2 text-xs font-medium text-gray-500 transition hover:border-gray-400 hover:text-gray-700"
              >
                <Plus className="h-3.5 w-3.5" />
                New Scorer
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
