export function formatTimestamp(ts: string | number): string {
  const value =
    typeof ts === 'number'
      ? new Date(ts > 2_000_000_000 ? ts : ts * 1000)
      : new Date(ts);
  const date = Number.isNaN(value.getTime()) ? new Date() : value;
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    year: 'numeric',
  });
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatScore(score: number): string {
  return score.toFixed(1);
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

export function classNames(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ');
}

export function scoreColor(score: number): string {
  if (score >= 80) return 'text-green-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-red-600';
}

export function scoreBgColor(score: number): string {
  if (score >= 80) return 'bg-green-500';
  if (score >= 60) return 'bg-amber-500';
  return 'bg-red-500';
}

export function statusVariant(status: string): 'success' | 'error' | 'warning' | 'pending' | 'running' {
  switch (status) {
    case 'completed':
    case 'accepted':
    case 'success':
    case 'active':
    case 'promote':
    case 'promoted':
      return 'success';
    case 'failed':
    case 'fail':
    case 'error':
    case 'failure':
    case 'rollback':
    case 'rolled_back':
      return 'error';
    case 'abandon':
    case 'rejected_quality':
    case 'rejected_safety':
    case 'rejected_no_improvement':
    case 'rejected_regression':
    case 'rejected_invalid':
    case 'rejected_noop':
    case 'warning':
    case 'degraded':
      return 'warning';
    case 'running':
      return 'running';
    default:
      return 'pending';
  }
}

export function statusLabel(status: string): string {
  return status.replaceAll('_', ' ');
}
