import { useMemo, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, BookOpen, Hammer, LayoutDashboard, PauseCircle, PlayCircle, ShieldCheck, Sparkles, X } from 'lucide-react';
import {
  useControlState,
  useCostHealth,
  useEvalSetHealth,
  useHealth,
  useOptimizeHistory,
  usePauseControl,
  usePinSurface,
  useRejectExperimentControl,
  useResumeControl,
  useUnpinSurface,
  useSystemEvents,
} from '../lib/api';
import { Confetti } from '../components/Confetti';
import { DiagnosisChat } from '../components/DiagnosisChat';
import { EmptyState } from '../components/EmptyState';
import { FixButton } from '../components/FixButton';
import { HealthPulse } from '../components/HealthPulse';
import { JourneyTimeline } from '../components/JourneyTimeline';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { ScoreChart } from '../components/ScoreChart';
import { StatusBadge } from '../components/StatusBadge';
import { formatLatency, formatPercent, formatTimestamp, statusVariant } from '../lib/utils';

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function ratioBarClass(value: number): string {
  if (value >= 0.85) return 'bg-green-500';
  if (value >= 0.65) return 'bg-amber-500';
  return 'bg-red-500';
}

function classNames(...classes: string[]): string {
  return classes.filter(Boolean).join(' ');
}

/**
 * Simplicity-first dashboard: 2 hard gates + 4 primary metrics.
 * Diagnostics in collapsible "Why?" panel.
 * Human escape hatches and cost controls always visible.
 *
 * Design principle (Researcher #2): "The power comes from iteration speed
 * and cycle count, not from the sophistication of any single component."
 */
export function Dashboard() {
  const navigate = useNavigate();

  // Core data
  const health = useHealth();
  const optimizeHistory = useOptimizeHistory();
  const controlState = useControlState();
  const costHealth = useCostHealth();
  const evalSetHealth = useEvalSetHealth();
  const events = useSystemEvents({ limit: 12 });

  // Mutations
  const pauseControl = usePauseControl();
  const resumeControl = useResumeControl();
  const pinSurface = usePinSurface();
  const unpinSurface = useUnpinSurface();
  const rejectExperiment = useRejectExperimentControl();

  const [surfaceInput, setSurfaceInput] = useState('prompts.root');
  const [rejectExperimentId, setRejectExperimentId] = useState('');
  const [showConfetti, setShowConfetti] = useState(false);
  const [allTimeBest, setAllTimeBest] = useState(0);
  const [viewMode, setViewMode] = useState<'simple' | 'advanced'>('simple');
  const [demoStatus, setDemoStatus] = useState<{ has_demo_data: boolean } | null>(null);
  const [showWelcome, setShowWelcome] = useState(() => {
    try {
      return localStorage.getItem('autoagent_welcome_dismissed') !== 'true';
    } catch {
      return true;
    }
  });

  const dismissWelcome = useCallback(() => {
    try {
      localStorage.setItem('autoagent_welcome_dismissed', 'true');
    } catch {
      // ignore
    }
    setShowWelcome(false);
  }, []);

  const loading = health.isLoading || controlState.isLoading;

  // Check for demo data
  useEffect(() => {
    fetch('/api/demo/status')
      .then((res) => res.json())
      .then((data) => setDemoStatus(data))
      .catch(() => setDemoStatus(null));
  }, []);

  const spendTrend = useMemo(() => {
    return (costHealth.data?.recent_cycles || []).map((row: { cycle_id: string; spent_dollars: number }) => ({
      label: row.cycle_id,
      score: Math.min(100, row.spent_dollars * 100),
    }));
  }, [costHealth.data?.recent_cycles]);

  // Detect personal best and trigger confetti
  useEffect(() => {
    const metrics = health.data?.metrics;
    if (metrics?.success_rate) {
      const currentScore = metrics.success_rate;
      if (currentScore > allTimeBest) {
        setAllTimeBest(currentScore);
        if (allTimeBest > 0) {
          // Only trigger confetti if we had a previous best (not on first load)
          setShowConfetti(true);
          setTimeout(() => setShowConfetti(false), 100);
        }
      }
    }
  }, [health.data?.metrics?.success_rate, allTimeBest]);

  function refreshAll() {
    health.refetch();
    optimizeHistory.refetch();
    controlState.refetch();
    costHealth.refetch();
    evalSetHealth.refetch();
    events.refetch();
  }

  function handlePauseResume() {
    if (controlState.data?.paused) {
      resumeControl.mutate(undefined);
      return;
    }
    pauseControl.mutate(undefined);
  }

  function handlePinSurface() {
    const surface = surfaceInput.trim();
    if (!surface) return;
    pinSurface.mutate({ surface });
  }

  function handleRejectExperiment() {
    const id = rejectExperimentId.trim();
    if (!id) return;
    rejectExperiment.mutate({ experiment_id: id });
    setRejectExperimentId('');
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={6} />
        <LoadingSkeleton rows={5} />
      </div>
    );
  }

  const metrics = health.data?.metrics;
  const history = optimizeHistory.data || [];

  const hasNoData = !metrics && history.length === 0;
  if (hasNoData) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Karpathy Loop Scorecard"
          description="Simplicity-first: 2 hard gates + 4 primary metrics."
        />
        <EmptyState
          icon={LayoutDashboard}
          title="No data yet"
          description="Run the quickstart command to seed data, evaluate your agent, and run your first optimization cycle."
          cliHint="autoagent quickstart"
        />
      </div>
    );
  }

  const attempts = history.slice().reverse();
  const trajectoryData = attempts.map((attempt, index) => ({
    label: `#${index + 1}`,
    score: attempt.score_after,
  }));

  // Derive hard gates and primary metrics from health data
  const safetyPassed = metrics ? metrics.safety_violation_rate === 0 : true;
  const latestAttempt = history.length > 0 ? history[0] : null;
  const regressionPassed = latestAttempt ? latestAttempt.status === 'accepted' || latestAttempt.status === 'rejected_noop' : true;

  return (
    <div className="space-y-6">
      <Confetti trigger={showConfetti} />

      {/* First-run Welcome Banner */}
      {showWelcome && (
        <div className="relative overflow-hidden rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50 via-violet-50 to-purple-50 p-5 shadow-sm">
          <button
            onClick={dismissWelcome}
            className="absolute right-3 top-3 rounded-md p-1 text-gray-400 transition hover:bg-white/60 hover:text-gray-600"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>

          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 shadow">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-semibold text-gray-900">Welcome to AutoAgent!</h3>
              <p className="mt-0.5 text-sm text-gray-600">
                Your dashboard is pre-loaded with demo data. Explore how the platform traces, diagnoses, and fixes agent failures automatically.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => { navigate('/build'); dismissWelcome(); }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-indigo-700 shadow-sm ring-1 ring-indigo-200 transition hover:bg-indigo-50 hover:ring-indigo-300"
                >
                  <Hammer className="h-3.5 w-3.5" />
                  Builder
                </button>
                <button
                  onClick={() => { navigate('/demo'); dismissWelcome(); }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-violet-700 shadow-sm ring-1 ring-violet-200 transition hover:bg-violet-50 hover:ring-violet-300"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  Run Demo
                </button>
                <a
                  href="/docs"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm ring-1 ring-gray-200 transition hover:bg-gray-50 hover:ring-gray-300"
                >
                  <BookOpen className="h-3.5 w-3.5" />
                  Docs
                </a>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Demo Data Banner */}
      {demoStatus?.has_demo_data && (
        <div className="rounded-lg border border-blue-200 bg-gradient-to-r from-blue-50 to-purple-50 p-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-gradient-to-br from-blue-500 to-purple-600 p-2">
                <Sparkles className="h-5 w-5 text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900">Demo scenario available</p>
                <p className="text-sm text-gray-600">
                  Explore the VP demo: E-commerce bot optimization from 0.62 → 0.87 health
                </p>
              </div>
            </div>
            <button
              onClick={() => navigate('/demo')}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 px-4 py-2 text-sm font-medium text-white shadow-lg transition hover:from-blue-700 hover:to-purple-700"
            >
              Explore Demo
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      <PageHeader
        title="Karpathy Loop Scorecard"
        description="Simplicity-first: 2 hard gates + 4 primary metrics. Diagnostics in collapsible panel. Human overrides always visible."
        actions={
          <>
            <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1">
              <button
                onClick={() => setViewMode('simple')}
                className={classNames(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  viewMode === 'simple'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                Simple
              </button>
              <button
                onClick={() => setViewMode('advanced')}
                className={classNames(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  viewMode === 'advanced'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                Advanced
              </button>
            </div>
            <button
              onClick={() => navigate('/build')}
              className="rounded-lg border border-sky-300 bg-sky-50 px-3.5 py-2 text-sm font-medium text-sky-800 transition hover:bg-sky-100"
            >
              Builder
            </button>
            <button
              onClick={() => navigate('/evals?new=1')}
              className="rounded-lg bg-gray-900 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-gray-800"
            >
              Run Eval
            </button>
            <button
              onClick={refreshAll}
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Refresh
            </button>
          </>
        }
      />

      {/* Health Pulse + Hard Gates */}
      <section className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          {/* Health Pulse */}
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <div className="flex justify-center">
              <HealthPulse score={metrics?.success_rate || 0} label="Agent Health" size="md" />
            </div>
          </div>

          {/* Hard Gates */}
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-gray-500" />
              <h3 className="text-sm font-semibold text-gray-900">Hard Gates</h3>
            </div>
          <div className="space-y-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs text-gray-500">Safety Gate</p>
              <div className="mt-1">
                <StatusBadge variant={safetyPassed ? 'success' : 'error'} label={safetyPassed ? 'Pass' : 'Fail'} />
              </div>
              <p className="mt-2 text-xs text-gray-600">Violation rate: {metrics ? formatPercent(metrics.safety_violation_rate) : '0%'}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs text-gray-500">Regression Gate</p>
              <div className="mt-1">
                <StatusBadge variant={regressionPassed ? 'success' : 'error'} label={regressionPassed ? 'Pass' : 'Fail'} />
              </div>
              <p className="mt-2 text-xs text-gray-600">Latest: {latestAttempt?.status?.replaceAll('_', ' ') || 'no runs'}</p>
            </div>
          </div>
        </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            title="Task Success"
            value={metrics ? formatPercent(metrics.success_rate) : '0%'}
            subtitle="primary outcome"
            trend={metrics && metrics.success_rate >= 0.8 ? 'up' : metrics && metrics.success_rate >= 0.65 ? 'neutral' : 'down'}
          />
          <MetricCard
            title="Error Rate"
            value={metrics ? formatPercent(metrics.error_rate) : '0%'}
            subtitle="failure frequency"
            trend={metrics && metrics.error_rate <= 0.05 ? 'up' : metrics && metrics.error_rate <= 0.15 ? 'neutral' : 'down'}
          />
          <MetricCard
            title="Latency p95"
            value={metrics ? formatLatency(metrics.avg_latency_ms) : '0ms'}
            subtitle="single p95 target"
            trend={metrics && metrics.avg_latency_ms <= 2000 ? 'up' : metrics && metrics.avg_latency_ms <= 3500 ? 'neutral' : 'down'}
          />
          <MetricCard
            title="Cost / Conversation"
            value={metrics ? `$${metrics.avg_cost.toFixed(4)}` : '$0'}
            subtitle="token-normalized spend"
            trend={metrics && metrics.avg_cost <= 0.02 ? 'up' : metrics && metrics.avg_cost <= 0.05 ? 'neutral' : 'down'}
          />
        </div>
      </section>

      {/* Diagnostics (collapsible) - only in Advanced mode */}
      {viewMode === 'advanced' && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <details open>
            <summary className="cursor-pointer select-none text-sm font-semibold text-gray-900">Why? Diagnostic Signals</summary>
            <div className="mt-4 space-y-4">
            {/* Metric bars */}
            <div className="grid gap-4 lg:grid-cols-3">
              {[
                { label: 'Error Rate', value: metrics ? 1 - metrics.error_rate : 1 },
                { label: 'Safety Compliance', value: metrics ? 1 - metrics.safety_violation_rate : 1 },
                { label: 'Latency Score', value: metrics ? Math.max(0, Math.min(1, 1 - metrics.avg_latency_ms / 5000)) : 1 },
              ].map((item) => (
                <div key={item.label} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>{item.label}</span>
                    <span className="tabular-nums">{percent(item.value)}</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-200">
                    <div
                      className={classNames('h-full rounded-full', ratioBarClass(item.value))}
                      style={{ width: `${Math.round(item.value * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Failure breakdown with fix buttons */}
            {metrics && (metrics.error_rate > 0 || metrics.safety_violation_rate > 0) && (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-gray-700">Common Failure Families</h4>
                <div className="space-y-2">
                  {metrics.error_rate > 0 && (
                    <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 p-3">
                      <div className="flex-1">
                        <span className="text-xs font-medium text-gray-700">routing_error</span>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-200">
                          <div
                            className="h-full rounded-full bg-red-500"
                            style={{ width: `${Math.round(metrics.error_rate * 100)}%` }}
                          />
                        </div>
                      </div>
                      <div className="ml-3">
                        <FixButton
                          failureFamily="routing_error"
                          failureCount={Math.round(metrics.error_rate * 100)}
                          onComplete={refreshAll}
                        />
                      </div>
                    </div>
                  )}
                  {metrics.safety_violation_rate > 0 && (
                    <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 p-3">
                      <div className="flex-1">
                        <span className="text-xs font-medium text-gray-700">safety_violation</span>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-200">
                          <div
                            className="h-full rounded-full bg-red-500"
                            style={{ width: `${Math.round(metrics.safety_violation_rate * 100)}%` }}
                          />
                        </div>
                      </div>
                      <div className="ml-3">
                        <FixButton
                          failureFamily="safety_violation"
                          failureCount={Math.round(metrics.safety_violation_rate * 100)}
                          onComplete={refreshAll}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </details>
        </section>
      )}

      {/* Journey Timeline */}
      {history.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Optimization Journey</h3>
            <button
              onClick={() => navigate('/optimize')}
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-800"
            >
              View full history
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
          <JourneyTimeline
            nodes={attempts.slice(0, 10).map((attempt: any, index: number) => ({
              version: `v${index + 1}`,
              score: attempt.score_after,
              change: attempt.change_description || 'Optimization change',
              status: attempt.status === 'accepted' ? 'accepted' : 'rejected',
              timestamp: attempt.timestamp || Date.now(),
            }))}
            onNodeClick={(version) => navigate(`/configs?v=${version}`)}
          />
        </section>
      )}

      {/* Score Trajectory */}
      {trajectoryData.length > 0 && (
        <section className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Score Trajectory</h3>
            <button
              onClick={() => navigate('/optimize')}
              className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-800"
            >
              View optimize history
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
          <ScoreChart data={trajectoryData} height={200} />
        </section>
      )}

      {/* Cost Controls + Human Escape Hatches - only in Advanced mode */}
      {viewMode === 'advanced' && (
        <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">Cost Controls</h3>
          <p className="mt-1 text-sm text-gray-600">Spend tracking and diminishing returns detection.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <MetricCard title="Total Spend" value={`$${(costHealth.data?.summary?.total_spend ?? 0).toFixed(3)}`} subtitle="all cycles" />
            <MetricCard title="Today Spend" value={`$${(costHealth.data?.summary?.today_spend ?? 0).toFixed(3)}`} subtitle="daily budget" />
            <MetricCard title="Cost / Improvement" value={`$${(costHealth.data?.summary?.cost_per_improvement ?? 0).toFixed(3)}`} subtitle="spend per lift" />
            <MetricCard title="Stall Guard" value={costHealth.data?.stall_detected ? 'Triggered' : 'Clear'} subtitle="stall detection" trend={costHealth.data?.stall_detected ? 'down' : 'up'} />
          </div>
          {spendTrend.length > 0 && (
            <div className="mt-4">
              <ScoreChart data={spendTrend} height={180} />
            </div>
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h3 className="text-sm font-semibold text-gray-900">Human Escape Hatches</h3>
          <p className="mt-1 text-sm text-gray-600">Pause loop, pin immutable surfaces, reject experiments.</p>

          <div className="mt-4 flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <div>
              <p className="text-xs text-gray-500">Optimizer state</p>
              <div className="mt-1">
                <StatusBadge
                  variant={statusVariant(controlState.data?.paused ? 'warning' : 'running')}
                  label={controlState.data?.paused ? 'paused' : 'running'}
                />
              </div>
            </div>
            <button
              onClick={handlePauseResume}
              disabled={pauseControl.isPending || resumeControl.isPending}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            >
              {controlState.data?.paused ? <PlayCircle className="h-4 w-4" /> : <PauseCircle className="h-4 w-4" />}
              {controlState.data?.paused ? 'Resume' : 'Pause'}
            </button>
          </div>

          <div className="mt-4 space-y-2">
            <label className="text-xs text-gray-500">Pin immutable surface</label>
            <div className="flex gap-2">
              <input
                value={surfaceInput}
                onChange={(event) => setSurfaceInput(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <button
                onClick={handlePinSurface}
                className="rounded-lg bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-800"
              >
                Pin
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(controlState.data?.immutable_surfaces?.length ?? 0) > 0 ? (
                controlState.data!.immutable_surfaces.map((surface: string) => (
                  <button
                    key={surface}
                    onClick={() => unpinSurface.mutate({ surface })}
                    className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700 hover:bg-blue-100"
                  >
                    {surface} &middot; unpin
                  </button>
                ))
              ) : (
                <span className="text-xs text-gray-500">No pinned surfaces.</span>
              )}
            </div>
          </div>

          <div className="mt-4 space-y-2">
            <label className="text-xs text-gray-500">Reject promoted experiment</label>
            <div className="flex gap-2">
              <input
                value={rejectExperimentId}
                onChange={(event) => setRejectExperimentId(event.target.value)}
                placeholder="experiment_id"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none"
              />
              <button
                onClick={handleRejectExperiment}
                className="rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
        </section>
      )}

      {/* Event Timeline */}
      <section className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Event Timeline</h3>
          <button
            onClick={() => navigate('/events')}
            className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-800"
          >
            Open full log
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="space-y-2">
          {events.data && events.data.length > 0 ? (
            events.data.map((event: { id: number; event_type: string; timestamp: number; cycle_id?: string }) => (
              <div key={event.id} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-gray-700">{event.event_type}</p>
                  <p className="text-xs text-gray-500">{formatTimestamp(event.timestamp)}</p>
                </div>
                {event.cycle_id && <p className="mt-0.5 text-xs text-gray-500">cycle: {event.cycle_id}</p>}
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-3 py-6 text-center text-sm text-gray-500">
              No events recorded yet. Events appear after optimization cycles run.
            </div>
          )}
        </div>
      </section>

      {/* Stall Warning */}
      {costHealth.data?.stall_detected && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-700" />
            <div>
              <p className="text-sm font-semibold text-amber-800">Diminishing returns detected</p>
              <p className="mt-1 text-sm text-amber-700">
                No significant improvement over the configured stall window. Consider pausing and rebalancing the eval set.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Anomalies from health */}
      {health.data?.anomalies && health.data.anomalies.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-800">Anomalies Detected</h3>
          <ul className="mt-2 space-y-1">
            {health.data.anomalies.map((anomaly: string, index: number) => (
              <li key={index} className="text-sm text-amber-700">
                {anomaly}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Diagnosis Chat Widget */}
      <DiagnosisChat />
    </div>
  );
}
