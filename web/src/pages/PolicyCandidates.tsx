import { useState, useEffect } from 'react';
import { GitBranch, Plus, Play, TrendingUp, RotateCcw, ChevronRight, X } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { classNames, formatTimestamp, statusVariant } from '../lib/utils';

const API_BASE = '/api';

interface PolicyArtifact {
  id: string;
  name: string;
  version: string;
  status: 'candidate' | 'canary' | 'promoted' | 'rolled_back';
  backend: string;
  dataset_path: string;
  created_at: string;
  ope_score?: number;
}

interface TrainingJob {
  id: string;
  mode: string;
  backend: string;
  dataset_path: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  created_at: string;
  policy_id?: string;
}

interface OPEReport {
  policy_id: string;
  baseline_score: number;
  candidate_score: number;
  uplift: number;
  uncertainty_low: number;
  uncertainty_high: number;
  coverage: number;
}

interface RawPolicyArtifact {
  policy_id?: string;
  name?: string;
  version?: number;
  status?: PolicyArtifact['status'];
  trainer_backend?: string;
  training_dataset_version?: string;
  created_at?: string;
  ope_report?: {
    candidate_estimated_uplift?: number;
  };
}

interface RawTrainingJob {
  job_id?: string;
  mode?: string;
  backend?: string;
  dataset_path?: string;
  status?: TrainingJob['status'];
  created_at?: string;
  policy_id?: string;
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const statusColors: Record<PolicyArtifact['status'], string> = {
  candidate: 'bg-gray-100 text-gray-700 border-gray-200',
  canary:    'bg-amber-50 text-amber-700 border-amber-200',
  promoted:  'bg-green-50 text-green-700 border-green-200',
  rolled_back: 'bg-red-50 text-red-700 border-red-200',
};

const defaultTrainForm = {
  mode: 'control',
  backend: 'vertex_sft',
  dataset_path: '',
};

const trainingModes = ['control', 'verifier', 'preference'] as const;
const backendsByMode = {
  control: ['vertex_sft', 'vertex_continuous'],
  verifier: ['openai_rft', 'vertex_sft', 'vertex_continuous'],
  preference: ['openai_dpo', 'vertex_preference', 'vertex_continuous'],
} as const;

function normalizePolicyArtifact(raw: RawPolicyArtifact): PolicyArtifact {
  return {
    id: raw.policy_id ?? 'unknown',
    name: raw.name ?? 'unnamed',
    version: String(raw.version ?? 1),
    status: raw.status ?? 'candidate',
    backend: raw.trainer_backend ?? 'unknown',
    dataset_path: raw.training_dataset_version ?? '',
    created_at: raw.created_at ?? new Date().toISOString(),
    ope_score: raw.ope_report?.candidate_estimated_uplift,
  };
}

function normalizeTrainingJob(raw: RawTrainingJob): TrainingJob {
  return {
    id: raw.job_id ?? 'unknown',
    mode: raw.mode ?? 'control',
    backend: raw.backend ?? 'unknown',
    dataset_path: raw.dataset_path ?? '',
    status: raw.status ?? 'pending',
    created_at: raw.created_at ?? new Date().toISOString(),
    policy_id: raw.policy_id,
  };
}

function normalizeOpeReport(payload: unknown): OPEReport {
  const wrapper = (typeof payload === 'object' && payload !== null)
    ? payload as {
        report?: {
          policy_id?: string;
          baseline_replay_score?: number;
          candidate_estimated_uplift?: number;
          uncertainty_lower?: number;
          uncertainty_upper?: number;
          support_coverage?: number;
        };
      }
    : {};
  const report = wrapper.report ?? {};
  const baseline = report.baseline_replay_score ?? 0;
  const uplift = report.candidate_estimated_uplift ?? 0;

  return {
    policy_id: report.policy_id ?? '',
    baseline_score: baseline,
    candidate_score: baseline + uplift,
    uplift,
    uncertainty_low: report.uncertainty_lower ?? 0,
    uncertainty_high: report.uncertainty_upper ?? 0,
    coverage: report.support_coverage ?? 0,
  };
}

export function PolicyCandidates() {
  const [policies, setPolicies] = useState<PolicyArtifact[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showTrainForm, setShowTrainForm] = useState(false);
  const [trainForm, setTrainForm] = useState({ ...defaultTrainForm });
  const [submitting, setSubmitting] = useState(false);

  const [selected, setSelected] = useState<PolicyArtifact | null>(null);
  const [opeReport, setOpeReport] = useState<OPEReport | null>(null);
  const [opeLoading, setOpeLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const trainingBackends = backendsByMode[trainForm.mode];

  async function loadPolicyData(selectedId?: string) {
    setLoading(true);
    try {
      const [policiesPayload, jobsPayload] = await Promise.all([
        fetchJson<{ policies?: RawPolicyArtifact[] }>('/rl/policies'),
        fetchJson<{ jobs?: RawTrainingJob[] }>('/rl/jobs'),
      ]);
      const nextPolicies = (policiesPayload.policies ?? []).map(normalizePolicyArtifact);
      const nextJobs = (jobsPayload.jobs ?? []).map(normalizeTrainingJob);
      setPolicies(nextPolicies);
      setJobs(nextJobs);
      if (selectedId) {
        setSelected(nextPolicies.find((policy) => policy.id === selectedId) ?? null);
      }
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPolicyData();
  }, []);

  async function startTraining() {
    if (!trainForm.dataset_path.trim()) return;
    setSubmitting(true);
    try {
      await fetchJson('/rl/train', {
        method: 'POST',
        body: JSON.stringify(trainForm),
      });
      await loadPolicyData(selected?.id);
      setTrainForm({ ...defaultTrainForm });
      setShowTrainForm(false);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start training job');
    } finally {
      setSubmitting(false);
    }
  }

  async function runOPE(policy: PolicyArtifact) {
    setOpeLoading(true);
    setOpeReport(null);
    try {
      const payload = await fetchJson<unknown>('/rl/ope', {
        method: 'POST',
        body: JSON.stringify({ policy_id: policy.id }),
      });
      setOpeReport(normalizeOpeReport(payload));
      await loadPolicyData(policy.id);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to run OPE');
    } finally {
      setOpeLoading(false);
    }
  }

  async function policyAction(action: 'promote' | 'rollback' | 'canary', policy: PolicyArtifact) {
    setActionLoading(action);
    try {
      await fetchJson(`/rl/${action}`, {
        method: 'POST',
        body: JSON.stringify({ policy_id: policy.id }),
      });
      await loadPolicyData(policy.id);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Failed to ${action} policy`);
    } finally {
      setActionLoading(null);
    }
  }

  function trainField(key: keyof typeof trainForm, value: string) {
    setTrainForm((prev) => {
      if (key !== 'mode') {
        return { ...prev, [key]: value };
      }

      const nextMode = value as typeof trainingModes[number];
      const compatibleBackends = backendsByMode[nextMode];
      const nextBackend = compatibleBackends.includes(prev.backend as typeof compatibleBackends[number])
        ? prev.backend
        : compatibleBackends[0];

      return { ...prev, mode: nextMode, backend: nextBackend };
    });
  }

  const upliftColor = (uplift: number) =>
    uplift > 0 ? 'text-green-700' : uplift < 0 ? 'text-red-700' : 'text-gray-700';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policy Candidates"
        description="Manage RL training jobs, evaluate policy artifacts with OPE, and promote or roll back candidates."
        actions={
          <button
            onClick={() => setShowTrainForm(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
          >
            <Plus className="h-4 w-4" />
            New Training Job
          </button>
        }
      />

      {/* Train form */}
      {showTrainForm && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Start Training Job</h3>
            <button
              onClick={() => setShowTrainForm(false)}
              className="rounded p-1 text-gray-500 hover:bg-gray-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs text-gray-500">Mode</label>
              <select
                value={trainForm.mode}
                onChange={(e) => trainField('mode', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                {trainingModes.map((mode) => (
                  <option key={mode} value={mode}>{mode}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Backend</label>
              <select
                value={trainForm.backend}
                onChange={(e) => trainField('backend', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                {trainingBackends.map((backend) => (
                  <option key={backend} value={backend}>{backend}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Dataset Path *</label>
              <input
                value={trainForm.dataset_path}
                onChange={(e) => trainField('dataset_path', e.target.value)}
                placeholder="e.g. s3://bucket/dataset.jsonl"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              onClick={startTraining}
              disabled={submitting || !trainForm.dataset_path.trim()}
              className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              {submitting ? 'Submitting...' : 'Start Job'}
            </button>
          </div>
        </section>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Policy artifacts */}
        <section>
          <h3 className="mb-3 text-sm font-semibold text-gray-900">
            Policy Artifacts {policies.length > 0 && `(${policies.length})`}
          </h3>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-20 animate-pulse rounded-lg border border-gray-200 bg-gray-100" />
              ))}
            </div>
          ) : policies.length === 0 ? (
            <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No policy artifacts yet. Start a training job to create one.
            </div>
          ) : (
            <div className="space-y-2">
              {policies.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { setSelected(p); setOpeReport(null); }}
                  className={classNames(
                    'w-full rounded-lg border p-3.5 text-left transition-colors',
                    selected?.id === p.id
                      ? 'border-blue-300 bg-blue-50'
                      : 'border-gray-200 bg-white hover:bg-gray-50'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <GitBranch className="h-4 w-4 text-gray-400" />
                      <span className="text-sm font-medium text-gray-900">{p.name}</span>
                      <span className="text-xs text-gray-400">v{p.version}</span>
                    </div>
                    <ChevronRight className="h-4 w-4 text-gray-400" />
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <span
                      className={classNames(
                        'rounded border px-1.5 py-0.5 text-[11px] font-medium',
                        statusColors[p.status]
                      )}
                    >
                      {p.status.replace('_', ' ')}
                    </span>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <span>{p.backend}</span>
                      {p.ope_score !== undefined && (
                        <span className="font-medium text-gray-700">{p.ope_score.toFixed(3)}</span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Training jobs */}
        <section>
          <h3 className="mb-3 text-sm font-semibold text-gray-900">
            Training Jobs {jobs.length > 0 && `(${jobs.length})`}
          </h3>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-20 animate-pulse rounded-lg border border-gray-200 bg-gray-100" />
              ))}
            </div>
          ) : jobs.length === 0 ? (
            <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No training jobs yet.
            </div>
          ) : (
            <div className="space-y-2">
              {jobs.map((j) => (
                <div key={j.id} className="rounded-lg border border-gray-200 bg-white p-3.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Play className="h-3.5 w-3.5 text-gray-400" />
                      <span className="text-sm font-medium text-gray-900 uppercase">{j.mode}</span>
                      <span className="text-xs text-gray-500">· {j.backend}</span>
                    </div>
                    <StatusBadge variant={statusVariant(j.status)} label={j.status} />
                  </div>
                  <p className="mt-1.5 break-all font-mono text-xs leading-relaxed text-gray-500">
                    {j.dataset_path}
                  </p>
                  <p className="mt-1 text-[11px] text-gray-400">{formatTimestamp(j.created_at)}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* Detail panel */}
      {selected && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-gray-900">
              {selected.name} <span className="font-normal text-gray-500">v{selected.version}</span>
            </h3>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => runOPE(selected)}
                disabled={opeLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
              >
                <TrendingUp className="h-3.5 w-3.5" />
                {opeLoading ? 'Evaluating...' : 'Run OPE'}
              </button>
              {selected.status !== 'canary' && selected.status !== 'promoted' && (
                <button
                  onClick={() => policyAction('canary', selected)}
                  disabled={actionLoading !== null}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition hover:bg-amber-100 disabled:opacity-60"
                >
                  {actionLoading === 'canary' ? 'Setting...' : 'Canary'}
                </button>
              )}
              {selected.status !== 'promoted' && (
                <button
                  onClick={() => policyAction('promote', selected)}
                  disabled={actionLoading !== null || selected.ope_score === undefined}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-green-700 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-green-800 disabled:opacity-60"
                  title={selected.ope_score === undefined ? 'Run OPE before promoting this policy' : undefined}
                >
                  {actionLoading === 'promote' ? 'Promoting...' : 'Promote'}
                </button>
              )}
              {selected.status !== 'rolled_back' && selected.status !== 'candidate' && (
                <button
                  onClick={() => policyAction('rollback', selected)}
                  disabled={actionLoading !== null}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 transition hover:bg-red-100 disabled:opacity-60"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {actionLoading === 'rollback' ? 'Rolling back...' : 'Rollback'}
                </button>
              )}
            </div>
          </div>

          <dl className="grid gap-2 sm:grid-cols-4 text-sm">
            {(['status', 'backend', 'version'] as const).map((k) => (
              <div key={k} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <dt className="text-xs text-gray-500 capitalize">{k}</dt>
                <dd className="mt-0.5 font-medium text-gray-900">{String(selected[k])}</dd>
              </div>
            ))}
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
              <dt className="text-xs text-gray-500">Created</dt>
              <dd className="mt-0.5 text-xs font-medium text-gray-900">{formatTimestamp(selected.created_at)}</dd>
            </div>
          </dl>

          {/* OPE report */}
          {opeReport && (
            <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <h4 className="mb-3 text-sm font-semibold text-gray-900">OPE Report</h4>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">Baseline Score</p>
                  <p className="mt-1 text-xl font-semibold text-gray-900">{opeReport.baseline_score.toFixed(4)}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">Candidate Score</p>
                  <p className="mt-1 text-xl font-semibold text-gray-900">{opeReport.candidate_score.toFixed(4)}</p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">Uplift</p>
                  <p className={classNames('mt-1 text-xl font-semibold', upliftColor(opeReport.uplift))}>
                    {opeReport.uplift >= 0 ? '+' : ''}{opeReport.uplift.toFixed(4)}
                  </p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-white p-3">
                  <p className="text-xs text-gray-500">Coverage</p>
                  <p className="mt-1 text-xl font-semibold text-gray-900">{(opeReport.coverage * 100).toFixed(1)}%</p>
                </div>
              </div>
              <p className="mt-2 text-xs text-gray-500">
                95% CI: [{opeReport.uncertainty_low.toFixed(4)}, {opeReport.uncertainty_high.toFixed(4)}]
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default PolicyCandidates;
