import { useNavigate } from 'react-router-dom';
import { Activity, ArrowRight, BarChart3 } from 'lucide-react';
import { useHealth, useOptimizeHistory } from '../lib/api';
import { MetricCard } from '../components/MetricCard';
import { ScoreChart } from '../components/ScoreChart';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../components/PageHeader';
import { ScoreRing } from '../components/ScoreRing';
import { TimelineEntry } from '../components/TimelineEntry';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { formatLatency, formatPercent, statusVariant } from '../lib/utils';

function calculateHealthScore(args: {
  successRate: number;
  errorRate: number;
  safetyViolationRate: number;
  latencyMs: number;
}): number {
  const latencyScore = Math.max(0, Math.min(1, 1 - args.latencyMs / 5000));
  const weighted =
    args.successRate * 0.45 +
    (1 - args.errorRate) * 0.25 +
    (1 - args.safetyViolationRate) * 0.2 +
    latencyScore * 0.1;
  return Math.max(0, Math.min(100, weighted * 100));
}

export function Dashboard() {
  const navigate = useNavigate();
  const { data: health, isLoading: healthLoading, refetch, isError } = useHealth();
  const { data: history, isLoading: historyLoading } = useOptimizeHistory();

  if (healthLoading || historyLoading) {
    return (
      <div className="space-y-4">
        <LoadingSkeleton rows={5} />
        <LoadingSkeleton rows={4} />
      </div>
    );
  }

  if (!health || health.metrics.total_conversations === 0) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No health data yet"
        description="Run your first evaluation to establish baseline quality, safety, latency, and cost metrics."
        actionLabel="Create first eval"
        onAction={() => navigate('/evals?new=1')}
      />
    );
  }

  const metrics = health.metrics;
  const healthScore = calculateHealthScore({
    successRate: metrics.success_rate,
    errorRate: metrics.error_rate,
    safetyViolationRate: metrics.safety_violation_rate,
    latencyMs: metrics.avg_latency_ms,
  });

  const attempts = (history || []).slice().reverse();
  const trajectoryData = attempts.map((attempt, index) => ({
    label: `#${index + 1}`,
    score: attempt.score_after,
  }));

  const recentAttempts = (history || []).slice(0, 5);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Health"
        description="Operational quality snapshot across production conversations and optimization history."
        actions={
          <>
            <button
              onClick={() => navigate('/evals?new=1')}
              className="rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
            >
              New Eval
            </button>
            <button
              onClick={() => refetch()}
              className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
            >
              Refresh
            </button>
          </>
        }
      />

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Health data could not be refreshed. Try again in a moment.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <ScoreRing
          score={healthScore}
          label="Composite system health"
          sublabel="Weighted blend of success rate, error rate, safety violations, and latency posture."
        />

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <MetricCard
            title="Success Rate"
            value={formatPercent(metrics.success_rate)}
            trend={metrics.success_rate >= 0.85 ? 'up' : metrics.success_rate >= 0.7 ? 'neutral' : 'down'}
            trendValue={metrics.success_rate >= 0.85 ? 'Strong' : metrics.success_rate >= 0.7 ? 'Stable' : 'Needs work'}
            subtitle="conversation outcomes"
            sparklineData={(history || []).slice(0, 8).map((attempt) => attempt.score_after)}
          />
          <MetricCard
            title="Avg Latency"
            value={formatLatency(metrics.avg_latency_ms)}
            trend={metrics.avg_latency_ms <= 1500 ? 'up' : metrics.avg_latency_ms <= 2800 ? 'neutral' : 'down'}
            trendValue={metrics.avg_latency_ms <= 1500 ? 'Fast' : metrics.avg_latency_ms <= 2800 ? 'Watch' : 'Slow'}
            subtitle="response speed"
          />
          <MetricCard
            title="Error Rate"
            value={formatPercent(metrics.error_rate)}
            trend={metrics.error_rate <= 0.08 ? 'up' : metrics.error_rate <= 0.15 ? 'neutral' : 'down'}
            trendValue={metrics.error_rate <= 0.08 ? 'Healthy' : metrics.error_rate <= 0.15 ? 'Elevated' : 'High'}
            subtitle="failed + error + abandon"
          />
          <MetricCard
            title="Safety Violations"
            value={formatPercent(metrics.safety_violation_rate)}
            trend={metrics.safety_violation_rate === 0 ? 'up' : 'down'}
            trendValue={metrics.safety_violation_rate === 0 ? 'Zero' : 'Review'}
            subtitle="must stay at zero"
          />
          <MetricCard
            title="Avg Cost"
            value={`$${metrics.avg_cost.toFixed(4)}`}
            trend="neutral"
            subtitle="per conversation"
          />
          <MetricCard
            title="Conversations"
            value={metrics.total_conversations.toLocaleString()}
            trend="neutral"
            subtitle="total observed"
          />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
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
          {trajectoryData.length > 0 ? (
            <ScoreChart data={trajectoryData} height={280} />
          ) : (
            <div className="flex h-[280px] items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No optimization runs yet.
            </div>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">Recent Optimization Activity</h3>
          {recentAttempts.length > 0 ? (
            <div className="space-y-3">
              {recentAttempts.map((attempt) => (
                <div key={attempt.attempt_id} className="rounded-lg border border-gray-200 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900">{attempt.change_description || 'Attempt update'}</p>
                    <StatusBadge variant={statusVariant(attempt.status)} label={attempt.status.replaceAll('_', ' ')} />
                  </div>
                  <p className="mt-1 text-xs text-gray-600">
                    {attempt.score_before.toFixed(1)} → {attempt.score_after.toFixed(1)}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-36 items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
              No optimization attempts yet.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Timeline</h3>
          <Activity className="h-4 w-4 text-gray-400" />
        </div>
        <div className="space-y-3 border-l border-dashed border-gray-200 pl-2">
          {recentAttempts.length > 0 ? (
            recentAttempts.map((attempt) => (
              <TimelineEntry
                key={attempt.attempt_id}
                timestamp={attempt.timestamp}
                title={`Optimization ${attempt.attempt_id.slice(0, 8)}`}
                description={attempt.change_description}
                status={attempt.status}
              />
            ))
          ) : (
            <p className="text-sm text-gray-500">Timeline will populate after your first optimization cycle.</p>
          )}
        </div>
      </div>

      {health.anomalies.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-800">Anomalies Detected</h3>
          <ul className="mt-2 space-y-1">
            {health.anomalies.map((anomaly, index) => (
              <li key={index} className="text-sm text-amber-700">
                {anomaly}
              </li>
            ))}
          </ul>
          {health.reason && <p className="mt-2 text-xs text-amber-700">Recommendation: {health.reason}</p>}
        </div>
      )}
    </div>
  );
}
