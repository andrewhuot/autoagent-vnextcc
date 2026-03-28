import { useState } from 'react';
import { Shield, AlertTriangle, CheckCircle, TrendingUp, Play, FlaskConical } from 'lucide-react';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';
import { classNames } from '../lib/utils';

const API_BASE = '/api';

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

interface OPEReport {
  policy_id: string;
  baseline_score: number;
  candidate_score: number;
  uplift: number;
  uncertainty_low: number;
  uncertainty_high: number;
  coverage: number;
}

interface SycophancyResult {
  reward_name: string;
  score: number;
  flagged: boolean;
  examples: { prompt: string; sycophantic: string; honest: string; delta: number }[];
}

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

const severityConfig = {
  critical: {
    icon: <AlertTriangle className="h-3.5 w-3.5 text-red-500" />,
    row: 'border-red-100 bg-red-50',
    label: 'text-red-700',
  },
  warning: {
    icon: <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />,
    row: 'border-amber-100 bg-amber-50',
    label: 'text-amber-700',
  },
  info: {
    icon: <CheckCircle className="h-3.5 w-3.5 text-blue-500" />,
    row: 'border-blue-100 bg-blue-50',
    label: 'text-blue-700',
  },
};

export function RewardAudit() {
  const [rewardName, setRewardName] = useState('');
  const [policyId, setPolicyId] = useState('');

  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);

  const [challengeReport, setChallengeReport] = useState<ChallengeReport | null>(null);
  const [challengeLoading, setChallengeLoading] = useState(false);

  const [opeReport, setOpeReport] = useState<OPEReport | null>(null);
  const [opeLoading, setOpeLoading] = useState(false);

  const [sycophancy, setSycophancy] = useState<SycophancyResult | null>(null);
  const [sycLoading, setSycLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  async function runAudit() {
    if (!rewardName.trim()) return;
    setAuditLoading(true);
    setAuditResult(null);
    setError(null);
    try {
      const result = await fetchJson<AuditResult>(`/rewards/${rewardName.trim()}/audit`, { method: 'POST' });
      setAuditResult(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Audit failed');
    } finally {
      setAuditLoading(false);
    }
  }

  async function runChallenge() {
    setChallengeLoading(true);
    setChallengeReport(null);
    setError(null);
    try {
      const body = rewardName.trim() ? JSON.stringify({ reward_name: rewardName.trim() }) : undefined;
      const report = await fetchJson<ChallengeReport>('/rewards/challenge/run', { method: 'POST', body });
      setChallengeReport(report);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Challenge run failed');
    } finally {
      setChallengeLoading(false);
    }
  }

  async function runOPE() {
    if (!policyId.trim()) return;
    setOpeLoading(true);
    setOpeReport(null);
    setError(null);
    try {
      const report = await fetchJson<OPEReport>('/rl/ope', {
        method: 'POST',
        body: JSON.stringify({ policy_id: policyId.trim() }),
      });
      setOpeReport(report);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'OPE failed');
    } finally {
      setOpeLoading(false);
    }
  }

  async function runSycophancy() {
    if (!rewardName.trim()) return;
    setSycLoading(true);
    setSycophancy(null);
    setError(null);
    try {
      const result = await fetchJson<SycophancyResult>(`/rewards/${rewardName.trim()}/audit`, {
        method: 'POST',
        body: JSON.stringify({ test: 'sycophancy' }),
      });
      setSycophancy(result as unknown as SycophancyResult);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sycophancy test failed');
    } finally {
      setSycLoading(false);
    }
  }

  const upliftColor = (uplift: number) =>
    uplift > 0 ? 'text-green-700' : uplift < 0 ? 'text-red-700' : 'text-gray-700';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reward Audit"
        description="Run challenge suites, inspect audit findings, evaluate OPE reports, and detect sycophancy in reward models."
      />

      {/* Controls */}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">Run Evaluations</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-gray-500">Reward Name</label>
            <input
              value={rewardName}
              onChange={(e) => setRewardName(e.target.value)}
              placeholder="e.g. helpfulness_v2"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">Policy ID (for OPE)</label>
            <input
              value={policyId}
              onChange={(e) => setPolicyId(e.target.value)}
              placeholder="e.g. policy-abc123"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={runAudit}
            disabled={auditLoading || !rewardName.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
          >
            <Shield className="h-4 w-4" />
            {auditLoading ? 'Auditing...' : 'Audit Reward'}
          </button>
          <button
            onClick={runChallenge}
            disabled={challengeLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
          >
            <Play className="h-4 w-4" />
            {challengeLoading ? 'Running...' : 'Challenge Suite'}
          </button>
          <button
            onClick={runOPE}
            disabled={opeLoading || !policyId.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-60"
          >
            <TrendingUp className="h-4 w-4" />
            {opeLoading ? 'Evaluating...' : 'Run OPE'}
          </button>
          <button
            onClick={runSycophancy}
            disabled={sycLoading || !rewardName.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60"
          >
            <FlaskConical className="h-4 w-4" />
            {sycLoading ? 'Testing...' : 'Sycophancy Test'}
          </button>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Audit findings */}
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center gap-2">
            <Shield className="h-4 w-4 text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900">Audit Findings</h3>
            {auditResult && (
              <StatusBadge
                variant={auditResult.passed ? 'success' : 'error'}
                label={auditResult.passed ? 'passed' : 'failed'}
              />
            )}
          </div>
          {!auditResult ? (
            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              Run an audit to see findings.
            </div>
          ) : auditResult.findings.length === 0 ? (
            <div className="flex h-32 items-center justify-center gap-2 rounded-lg border border-green-200 bg-green-50 text-sm text-green-700">
              <CheckCircle className="h-4 w-4" />
              No issues found — reward definition is clean.
            </div>
          ) : (
            <div className="space-y-1.5">
              {auditResult.findings.map((f, i) => {
                const cfg = severityConfig[f.severity];
                return (
                  <div
                    key={i}
                    className={classNames('flex items-start gap-2 rounded-lg border px-3 py-2', cfg.row)}
                  >
                    {cfg.icon}
                    <div>
                      <span className={classNames('text-[10px] font-semibold uppercase', cfg.label)}>
                        {f.severity}
                      </span>
                      <p className="text-xs text-gray-700">{f.message}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Challenge suite */}
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 flex items-center gap-2">
            <Play className="h-4 w-4 text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900">Challenge Suite Results</h3>
            {challengeReport && (
              <StatusBadge
                variant={challengeReport.passed === challengeReport.total ? 'success' : 'warning'}
                label={`${challengeReport.passed}/${challengeReport.total}`}
              />
            )}
          </div>
          {!challengeReport ? (
            <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              Run challenge suite to see results.
            </div>
          ) : (
            <>
              <div className="mb-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Suite</p>
                <p className="mt-0.5 font-medium text-gray-900">{challengeReport.suite}</p>
                <div className="mt-2">
                  <div className="mb-1 flex justify-between text-xs text-gray-500">
                    <span>Pass rate</span>
                    <span>{challengeReport.passed}/{challengeReport.total}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
                    <div
                      className={classNames(
                        'h-full rounded-full transition-all',
                        challengeReport.passed === challengeReport.total ? 'bg-green-500' : 'bg-amber-500'
                      )}
                      style={{ width: `${(challengeReport.passed / Math.max(challengeReport.total, 1)) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
              {challengeReport.failures.length > 0 ? (
                <div>
                  <p className="mb-1.5 text-xs font-medium text-red-700">Failures</p>
                  <ul className="space-y-1">
                    {challengeReport.failures.map((f, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-gray-700">
                        <span className="mt-0.5 shrink-0 text-red-500">•</span>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-xs text-green-700">All challenges passed.</p>
              )}
            </>
          )}
        </section>
      </div>

      {/* OPE report */}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-3 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-900">OPE Report</h3>
        </div>
        {!opeReport ? (
          <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            Enter a Policy ID and run OPE to see the evaluation report.
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Baseline Score</p>
                <p className="mt-1 text-2xl font-semibold text-gray-900">{opeReport.baseline_score.toFixed(4)}</p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Candidate Score</p>
                <p className="mt-1 text-2xl font-semibold text-gray-900">{opeReport.candidate_score.toFixed(4)}</p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Uplift</p>
                <p className={classNames('mt-1 text-2xl font-semibold', upliftColor(opeReport.uplift))}>
                  {opeReport.uplift >= 0 ? '+' : ''}{opeReport.uplift.toFixed(4)}
                </p>
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-xs text-gray-500">Coverage</p>
                <p className="mt-1 text-2xl font-semibold text-gray-900">{(opeReport.coverage * 100).toFixed(1)}%</p>
              </div>
            </div>
            <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
              <p className="text-xs text-gray-500">
                95% Uncertainty Interval: &nbsp;
                <span className="font-medium text-gray-900">
                  [{opeReport.uncertainty_low.toFixed(4)}, {opeReport.uncertainty_high.toFixed(4)}]
                </span>
              </p>
              <div className="relative mt-2 h-2 overflow-hidden rounded-full bg-gray-200">
                {/* Render the CI band relative to [0, max(candidate, baseline) * 1.2] */}
                {(() => {
                  const max = Math.max(opeReport.candidate_score, opeReport.baseline_score) * 1.25 || 1;
                  const lowPct = (opeReport.uncertainty_low / max) * 100;
                  const highPct = (opeReport.uncertainty_high / max) * 100;
                  const candidatePct = (opeReport.candidate_score / max) * 100;
                  return (
                    <>
                      <div
                        className="absolute h-full bg-blue-200"
                        style={{ left: `${lowPct}%`, width: `${highPct - lowPct}%` }}
                      />
                      <div
                        className="absolute h-full w-0.5 bg-blue-600"
                        style={{ left: `${candidatePct}%` }}
                      />
                    </>
                  );
                })()}
              </div>
              <p className="mt-1 text-[11px] text-gray-400">
                Blue band = uncertainty interval · Line = candidate score
              </p>
            </div>
          </>
        )}
      </section>

      {/* Sycophancy test */}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-3 flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-gray-400" />
          <h3 className="text-sm font-semibold text-gray-900">Sycophancy Test Results</h3>
          {sycophancy && (
            <StatusBadge
              variant={sycophancy.flagged ? 'error' : 'success'}
              label={sycophancy.flagged ? 'sycophancy detected' : 'clean'}
            />
          )}
        </div>
        {!sycophancy ? (
          <div className="flex h-28 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
            Run sycophancy test to detect reward hacking via flattery.
          </div>
        ) : (
          <>
            <div className="mb-3 flex items-center gap-4 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
              <div>
                <p className="text-xs text-gray-500">Sycophancy Score</p>
                <p className={classNames(
                  'mt-0.5 text-xl font-semibold',
                  sycophancy.score > 0.5 ? 'text-red-700' : 'text-green-700'
                )}>
                  {sycophancy.score.toFixed(3)}
                </p>
              </div>
              <div className="text-xs text-gray-500">
                Score &gt; 0.5 indicates the reward model may be over-rewarding sycophantic responses.
              </div>
            </div>
            {sycophancy.examples && sycophancy.examples.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-gray-700">Sample Comparisons</p>
                {sycophancy.examples.map((ex, i) => (
                  <div key={i} className="rounded-lg border border-gray-100 bg-gray-50 p-3 text-xs">
                    <p className="mb-2 font-medium text-gray-700 line-clamp-1">Prompt: {ex.prompt}</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded border border-red-100 bg-red-50 px-2 py-1.5">
                        <p className="mb-0.5 text-[10px] font-semibold text-red-700">Sycophantic</p>
                        <p className="line-clamp-2 text-gray-700">{ex.sycophantic}</p>
                      </div>
                      <div className="rounded border border-green-100 bg-green-50 px-2 py-1.5">
                        <p className="mb-0.5 text-[10px] font-semibold text-green-700">Honest</p>
                        <p className="line-clamp-2 text-gray-700">{ex.honest}</p>
                      </div>
                    </div>
                    <p className={classNames(
                      'mt-1.5 text-[11px] font-medium',
                      ex.delta > 0 ? 'text-red-600' : 'text-green-600'
                    )}>
                      Reward delta: {ex.delta >= 0 ? '+' : ''}{ex.delta.toFixed(4)}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

export default RewardAudit;
