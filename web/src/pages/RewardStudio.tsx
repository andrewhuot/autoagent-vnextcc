import { useState, useEffect } from 'react';
import { Award, Plus, Shield, AlertTriangle, CheckCircle, X, Play } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { classNames } from '../lib/utils';

const API_BASE = '/api';

interface Reward {
  name: string;
  kind: string;
  scope: string;
  granularity: string;
  source: string;
  trust_tier: string;
  weight: number;
  hard_gate: boolean;
}

interface AuditFinding {
  severity: 'critical' | 'warning' | 'info';
  message: string;
}

interface AuditResult {
  reward_name: string;
  findings: AuditFinding[];
  passed: boolean;
}

interface ChallengeReport {
  suite: string;
  passed: number;
  total: number;
  failures: string[];
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const trustTierColors: Record<string, string> = {
  high: 'bg-green-50 text-green-700 border-green-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-red-50 text-red-700 border-red-200',
};

const severityIcon = {
  critical: <AlertTriangle className="h-3.5 w-3.5 text-red-500" />,
  warning: <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />,
  info: <CheckCircle className="h-3.5 w-3.5 text-blue-500" />,
};

const defaultForm: Omit<Reward, 'name'> & { name: string } = {
  name: '',
  kind: 'scalar',
  scope: 'turn',
  granularity: 'token',
  source: 'model',
  trust_tier: 'medium',
  weight: 1.0,
  hard_gate: false,
};

export function RewardStudio() {
  const [rewards, setRewards] = useState<Reward[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...defaultForm });
  const [creating, setCreating] = useState(false);

  const [selected, setSelected] = useState<Reward | null>(null);
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [auditing, setAuditing] = useState(false);

  const [challengeReport, setChallengeReport] = useState<ChallengeReport | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    fetchJson<Reward[]>('/rewards')
      .then(setRewards)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  async function createReward() {
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      const created = await fetchJson<Reward>('/rewards', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setRewards((prev) => [created, ...prev]);
      setForm({ ...defaultForm });
      setShowForm(false);
    } catch {
      // ignore, keep form open
    } finally {
      setCreating(false);
    }
  }

  async function runAudit(reward: Reward) {
    setAuditing(true);
    setAuditResult(null);
    try {
      const result = await fetchJson<AuditResult>(`/rewards/${reward.name}/audit`, { method: 'POST' });
      setAuditResult(result);
    } catch {
      // ignore
    } finally {
      setAuditing(false);
    }
  }

  async function runChallenge() {
    setRunning(true);
    setChallengeReport(null);
    try {
      const report = await fetchJson<ChallengeReport>('/rewards/challenge/run', { method: 'POST' });
      setChallengeReport(report);
    } catch {
      // ignore
    } finally {
      setRunning(false);
    }
  }

  function field(key: keyof typeof form, value: string | number | boolean) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reward Studio"
        description="Define, audit, and validate reward functions that drive RLHF training and policy optimization."
        actions={
          <button
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
          >
            <Plus className="h-4 w-4" />
            New Reward
          </button>
        }
      />

      {/* Create form */}
      {showForm && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Create Reward</h3>
            <button
              onClick={() => setShowForm(false)}
              className="rounded p-1 text-gray-500 hover:bg-gray-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs text-gray-500">Name *</label>
              <input
                value={form.name}
                onChange={(e) => field('name', e.target.value)}
                placeholder="e.g. helpfulness_v2"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            {(['kind', 'scope', 'granularity', 'source'] as const).map((key) => (
              <div key={key}>
                <label className="mb-1 block text-xs capitalize text-gray-500">{key}</label>
                <input
                  value={form[key]}
                  onChange={(e) => field(key, e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            ))}
            <div>
              <label className="mb-1 block text-xs text-gray-500">Trust Tier</label>
              <select
                value={form.trust_tier}
                onChange={(e) => field('trust_tier', e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-500">Weight</label>
              <input
                type="number"
                step="0.1"
                min="0"
                value={form.weight}
                onChange={(e) => field('weight', parseFloat(e.target.value))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div className="flex items-end pb-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.hard_gate}
                  onChange={(e) => field('hard_gate', e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                Hard Gate
              </label>
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <button
              onClick={createReward}
              disabled={creating || !form.name.trim()}
              className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
            >
              {creating ? 'Creating...' : 'Create Reward'}
            </button>
          </div>
        </section>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Reward grid */}
      <section>
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-32 animate-pulse rounded-lg border border-gray-200 bg-gray-100" />
            ))}
          </div>
        ) : rewards.length === 0 ? (
          <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            No rewards defined yet. Create one to get started.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {rewards.map((r) => (
              <button
                key={r.name}
                onClick={() => { setSelected(r); setAuditResult(null); }}
                className={classNames(
                  'rounded-lg border p-4 text-left transition-colors',
                  selected?.name === r.name
                    ? 'border-blue-300 bg-blue-50'
                    : 'border-gray-200 bg-white hover:bg-gray-50'
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Award className="h-4 w-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-900">{r.name}</span>
                  </div>
                  {r.hard_gate && (
                    <span className="flex items-center gap-1 rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">
                      <Shield className="h-3 w-3" /> gate
                    </span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{r.kind}</span>
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{r.scope}</span>
                  <span
                    className={classNames(
                      'rounded border px-1.5 py-0.5 text-[11px] font-medium',
                      trustTierColors[r.trust_tier] ?? 'bg-gray-50 text-gray-700 border-gray-200'
                    )}
                  >
                    {r.trust_tier}
                  </span>
                </div>
                <p className="mt-2 text-xs text-gray-500">weight: {r.weight} · source: {r.source}</p>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Detail panel */}
      {selected && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Reward: {selected.name}</h3>
            <div className="flex gap-2">
              <button
                onClick={() => runAudit(selected)}
                disabled={auditing}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
              >
                <Shield className="h-3.5 w-3.5" />
                {auditing ? 'Auditing...' : 'Run Audit'}
              </button>
              <button
                onClick={runChallenge}
                disabled={running}
                className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
              >
                <Play className="h-3.5 w-3.5" />
                {running ? 'Running...' : 'Challenge Suite'}
              </button>
            </div>
          </div>
          <dl className="grid gap-2 sm:grid-cols-4 text-sm">
            {(['kind', 'scope', 'granularity', 'source', 'trust_tier', 'weight'] as const).map((k) => (
              <div key={k} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <dt className="text-xs text-gray-500 capitalize">{k.replace('_', ' ')}</dt>
                <dd className="mt-0.5 font-medium text-gray-900">{String(selected[k])}</dd>
              </div>
            ))}
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
              <dt className="text-xs text-gray-500">Hard Gate</dt>
              <dd className="mt-0.5 font-medium text-gray-900">{selected.hard_gate ? 'Yes' : 'No'}</dd>
            </div>
          </dl>

          {/* Audit results */}
          {auditResult && (
            <div className="mt-4">
              <div className="mb-2 flex items-center gap-2">
                <StatusBadge variant={auditResult.passed ? 'success' : 'error'} label={auditResult.passed ? 'passed' : 'failed'} />
                <span className="text-sm font-medium text-gray-900">Audit Findings</span>
              </div>
              {auditResult.findings.length === 0 ? (
                <p className="text-xs text-gray-500">No findings — reward definition looks clean.</p>
              ) : (
                <div className="space-y-1.5">
                  {auditResult.findings.map((f, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                      {severityIcon[f.severity]}
                      <p className="text-xs text-gray-700">{f.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Challenge report */}
          {challengeReport && (
            <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900">Challenge Suite: {challengeReport.suite}</span>
                <StatusBadge
                  variant={challengeReport.passed === challengeReport.total ? 'success' : 'warning'}
                  label={`${challengeReport.passed}/${challengeReport.total} passed`}
                />
              </div>
              {challengeReport.failures.length > 0 && (
                <ul className="space-y-1 text-xs text-red-700">
                  {challengeReport.failures.map((f, i) => <li key={i}>• {f}</li>)}
                </ul>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default RewardStudio;
