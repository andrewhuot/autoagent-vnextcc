import { Rocket, CheckCircle, XCircle, AlertTriangle, RotateCcw, Activity } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer } from 'recharts';
import { classNames, formatTimestamp } from '../../lib/utils';

interface CanaryMetrics {
  success_rate: number;
  error_rate: number;
  p95_latency_ms: number;
  sample_size: number;
}

interface TimelineEvent {
  timestamp: number;
  event: string;
  status: 'success' | 'warning' | 'error';
}

export interface DeployData {
  deployment_id: string;
  status: 'pending' | 'in-progress' | 'canary' | 'completed' | 'rolled-back' | 'failed';
  progress: number;
  canary_metrics?: CanaryMetrics;
  baseline_metrics?: CanaryMetrics;
  canary_traffic_pct?: number;
  timeline: TimelineEvent[];
  started_at: number;
  completed_at?: number;
  can_rollback?: boolean;
  metric_trend?: number[];
}

interface DeployCardProps {
  data: DeployData;
  onRollback?: () => void;
}

export function DeployCard({ data, onRollback }: DeployCardProps) {
  const statusConfig = {
    pending: { label: 'Pending', icon: Activity, color: 'text-gray-600', bg: 'bg-gray-50' },
    'in-progress': { label: 'Deploying', icon: Rocket, color: 'text-blue-600', bg: 'bg-blue-50' },
    canary: { label: 'Canary Testing', icon: Activity, color: 'text-amber-600', bg: 'bg-amber-50' },
    completed: { label: 'Deployed', icon: CheckCircle, color: 'text-green-600', bg: 'bg-green-50' },
    'rolled-back': { label: 'Rolled Back', icon: RotateCcw, color: 'text-red-600', bg: 'bg-red-50' },
    failed: { label: 'Failed', icon: XCircle, color: 'text-red-600', bg: 'bg-red-50' },
  };

  const config = statusConfig[data.status];
  const Icon = config.icon;

  const isCanaryHealthy = () => {
    if (!data.canary_metrics || !data.baseline_metrics) return true;
    return (
      data.canary_metrics.success_rate >= data.baseline_metrics.success_rate * 0.95 &&
      data.canary_metrics.error_rate <= data.baseline_metrics.error_rate * 1.1
    );
  };

  const canaryHealthy = isCanaryHealthy();

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Header */}
      <div className={classNames('border-b border-gray-200 px-6 py-4', config.bg)}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Icon className={classNames('h-5 w-5', config.color)} />
              <h3 className="text-sm font-medium text-gray-900">Deployment {config.label}</h3>
            </div>
            <p className="mt-1 text-xs font-mono text-gray-500">{data.deployment_id}</p>
            <p className="mt-1 text-xs text-gray-500">
              Started {formatTimestamp(data.started_at)}
              {data.completed_at && ` • Completed ${formatTimestamp(data.completed_at)}`}
            </p>
          </div>

          {/* Rollback Button */}
          {data.can_rollback && onRollback && data.status !== 'rolled-back' && (
            <button
              onClick={onRollback}
              className="flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 transition hover:bg-red-100"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Rollback
            </button>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="px-6 py-4">
        <div className="flex items-center justify-between text-xs mb-2">
          <span className="font-medium text-gray-700">Deployment Progress</span>
          <span className="font-medium tabular-nums text-gray-900">{data.progress.toFixed(0)}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-gray-100">
          <div
            className={classNames(
              'h-full rounded-full transition-all duration-500',
              data.status === 'failed' || data.status === 'rolled-back' ? 'bg-red-500' :
              data.status === 'completed' ? 'bg-green-500' : 'bg-blue-500'
            )}
            style={{ width: `${data.progress}%` }}
          />
        </div>
      </div>

      {/* Canary Metrics */}
      {data.status === 'canary' && data.canary_metrics && data.baseline_metrics && (
        <div className="border-t border-gray-100 px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
              Canary Metrics ({data.canary_traffic_pct}% traffic)
            </p>
            {!canaryHealthy && (
              <span className="flex items-center gap-1 text-xs text-amber-600">
                <AlertTriangle className="h-3.5 w-3.5" />
                Degraded performance
              </span>
            )}
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-gray-500">Success Rate</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className={classNames(
                  'text-lg font-semibold tabular-nums',
                  data.canary_metrics.success_rate >= data.baseline_metrics.success_rate * 0.95 ? 'text-green-600' : 'text-red-600'
                )}>
                  {(data.canary_metrics.success_rate * 100).toFixed(1)}%
                </span>
                <span className="text-xs text-gray-400">
                  vs {(data.baseline_metrics.success_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>

            <div>
              <p className="text-xs text-gray-500">Error Rate</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className={classNames(
                  'text-lg font-semibold tabular-nums',
                  data.canary_metrics.error_rate <= data.baseline_metrics.error_rate * 1.1 ? 'text-green-600' : 'text-red-600'
                )}>
                  {(data.canary_metrics.error_rate * 100).toFixed(1)}%
                </span>
                <span className="text-xs text-gray-400">
                  vs {(data.baseline_metrics.error_rate * 100).toFixed(1)}%
                </span>
              </div>
            </div>

            <div>
              <p className="text-xs text-gray-500">P95 Latency</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className={classNames(
                  'text-lg font-semibold tabular-nums',
                  data.canary_metrics.p95_latency_ms <= data.baseline_metrics.p95_latency_ms * 1.2 ? 'text-green-600' : 'text-red-600'
                )}>
                  {data.canary_metrics.p95_latency_ms}ms
                </span>
                <span className="text-xs text-gray-400">
                  vs {data.baseline_metrics.p95_latency_ms}ms
                </span>
              </div>
            </div>
          </div>

          {/* Metric Trend */}
          {data.metric_trend && data.metric_trend.length > 1 && (
            <div className="mt-4 h-16 rounded-lg bg-gray-50 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.metric_trend.map((v, i) => ({ idx: i, value: v }))}>
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke={canaryHealthy ? '#16a34a' : '#dc2626'}
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <p className="mt-2 text-xs text-gray-500">
            {data.canary_metrics.sample_size.toLocaleString()} requests sampled
          </p>
        </div>
      )}

      {/* Timeline */}
      <div className="border-t border-gray-100 px-6 py-4">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-3">
          Timeline
        </p>
        <div className="space-y-2">
          {data.timeline.map((event, idx) => (
            <div key={idx} className="flex items-start gap-3">
              <div className={classNames(
                'flex-shrink-0 mt-0.5 h-1.5 w-1.5 rounded-full',
                event.status === 'success' ? 'bg-green-500' :
                event.status === 'warning' ? 'bg-amber-500' : 'bg-red-500'
              )} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-gray-900">{event.event}</p>
                <p className="text-xs text-gray-400">{formatTimestamp(event.timestamp)}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
